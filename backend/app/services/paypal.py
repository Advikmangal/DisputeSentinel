"""Sandbox REST client. Returned payment data is not a verified DB transaction.

services/payments.py compares server-fetched amounts/currency against the stored
transaction and persists order/capture IDs under database unique constraints.
"""

import re
import time
from decimal import Decimal
from threading import Lock
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.config import Settings

SANDBOX_URL = "https://api-m.sandbox.paypal.com"


class PayPalError(Exception):
    """Safe diagnostic: never includes response bodies, headers or credentials."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class PayPalClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        if settings.paypal_base_url != SANDBOX_URL:
            raise ValueError("Only PayPal Sandbox is supported")
        secret = settings.paypal_client_secret.get_secret_value()
        if any(not value or value.startswith("replace-") for value in
               (settings.paypal_client_id, secret)):
            raise ValueError("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in the root .env")
        self._auth = httpx.BasicAuth(settings.paypal_client_id, secret)
        self._http = httpx.Client(
            base_url=SANDBOX_URL, timeout=30.0, follow_redirects=False,
            transport=transport,
        )
        self._clock = clock
        self._token = ""
        self._expires_at = 0.0
        self._token_lock = Lock()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        self._http.close()

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.RequestError:
            raise PayPalError("PayPal network request failed; retry with the same request ID") from None

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        if not response.is_success:
            raise PayPalError(f"PayPal returned HTTP {response.status_code}", response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise PayPalError("PayPal returned invalid JSON") from None
        if not isinstance(data, dict):
            raise PayPalError("PayPal returned an unexpected JSON shape")
        return data

    def get_access_token(self) -> str:
        with self._token_lock:
            if self._token and self._clock() < self._expires_at:
                return self._token
            started = self._clock()
            data = self._json(self._send(
                "POST", "/v1/oauth2/token", auth=self._auth,
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            ))
            token, expires = data.get("access_token"), data.get("expires_in")
            if (not isinstance(token, str) or not token
                    or not isinstance(expires, (int, float)) or isinstance(expires, bool)
                    or not 0 < expires < float("inf")
                    or str(data.get("token_type", "")).lower() != "bearer"):
                raise PayPalError("PayPal returned an invalid OAuth token response")
            self._token = token
            self._expires_at = started + expires - min(30.0, expires / 10)
            return token

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(2):
            token = self.get_access_token()
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
                       **kwargs.get("headers", {})}
            response = self._send(method, path, **{**kwargs, "headers": headers})
            if response.status_code == 401 and attempt == 0:
                with self._token_lock:
                    if self._token == token:
                        self._token = ""
                continue
            return self._json(response)
        raise AssertionError("Unreachable")

    @staticmethod
    def _id(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,127}", value):
            raise ValueError("Invalid PayPal resource ID")
        return value

    def create_order(self, amount: str, currency: str, *, request_id: str) -> dict[str, Any]:
        """Reuse the same request_id and payload when retrying this logical order."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,38}", request_id):
            raise ValueError("request_id must be 1–38 letters, digits, underscores or hyphens")
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", amount) or Decimal(amount) <= 0:
            raise ValueError("amount must be a positive decimal string with at most two decimals")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be an uppercase three-letter code")
        return self._request(
            "POST", "/v2/checkout/orders",
            headers={"PayPal-Request-Id": request_id, "Prefer": "return=representation"},
            json={"intent": "CAPTURE", "purchase_units": [
                {"amount": {"currency_code": currency, "value": amount}}
            ]},
        )

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v2/checkout/orders/{self._id(order_id)}")

    def capture_order(self, order_id: str) -> dict[str, Any]:
        """Fetch first; completed orders are no-ops. Replays use a stable key.

        This returns raw PayPal data. The payment service verifies amount/currency
        and completed capture status before recording a payment as verified.
        """
        order = self.get_order(order_id)
        if order.get("status") == "COMPLETED":
            return order
        request_id = str(uuid5(NAMESPACE_URL, f"payoutsentinel:capture:{order_id}"))
        try:
            return self._request(
                "POST", f"/v2/checkout/orders/{self._id(order_id)}/capture",
                headers={"PayPal-Request-Id": request_id, "Prefer": "return=representation"},
                json={},
            )
        except PayPalError as error:
            # Another worker may have captured after our initial fetch.
            if error.status_code == 422:
                latest = self.get_order(order_id)
                if latest.get("status") == "COMPLETED":
                    return latest
            raise

    def list_disputes(self, *, page_size: int = 20, next_page_token: str | None = None) -> dict[str, Any]:
        """Return one page including PayPal's pagination metadata."""
        if not 1 <= page_size <= 50:
            raise ValueError("page_size must be between 1 and 50")
        params: dict[str, Any] = {"page_size": page_size}
        if next_page_token:
            params["next_page_token"] = next_page_token
        return self._request("GET", "/v1/customer/disputes", params=params)

    def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/customer/disputes/{self._id(dispute_id)}")
