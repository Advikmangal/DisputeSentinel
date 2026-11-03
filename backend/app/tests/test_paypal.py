import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.config import Settings
from app.services.paypal import PayPalClient, PayPalError, SANDBOX_URL


@pytest.fixture
def settings():
    return Settings(_env_file=None, paypal_client_id="test-client",
                    paypal_client_secret="test-secret")


def token(value="test-token", expires=100):
    return httpx.Response(200, json={"access_token": value, "expires_in": expires,
                                   "token_type": "Bearer"})


def test_token_cache_expiry_and_basic_auth(settings):
    calls = []
    now = [0.0]

    def handler(request):
        calls.append(request)
        assert request.url == f"{SANDBOX_URL}/v1/oauth2/token"
        assert request.headers["Authorization"].startswith("Basic ")
        assert request.content == b"grant_type=client_credentials"
        return token(f"token-{len(calls)}")

    with PayPalClient(settings, transport=httpx.MockTransport(handler), clock=lambda: now[0]) as client:
        assert client.get_access_token() == "token-1"
        now[0] = 89
        assert client.get_access_token() == "token-1"
        now[0] = 90
        assert client.get_access_token() == "token-2"
    assert len(calls) == 2


def test_concurrent_token_fetch_is_cached(settings):
    calls = []

    def handler(request):
        calls.append(request)
        return token()

    with PayPalClient(settings, transport=httpx.MockTransport(handler)) as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(lambda _: client.get_access_token(), range(16))) == ["test-token"] * 16
    assert len(calls) == 1


def test_order_and_dispute_endpoints(settings):
    calls = []

    def handler(request):
        assert request.url.host == "api-m.sandbox.paypal.com"
        if request.url.path == "/v1/oauth2/token":
            return token()
        assert request.headers["Authorization"] == "Bearer test-token"
        calls.append(request)
        return httpx.Response(200, json={"id": "ORDER-1", "status": "APPROVED", "items": []})

    with PayPalClient(settings, transport=httpx.MockTransport(handler)) as client:
        client.create_order("1.00", "USD", request_id="logical-order-1")
        client.create_order("1.00", "USD", request_id="logical-order-1")
        client.get_order("ORDER-1")
        client.capture_order("ORDER-1")
        client.capture_order("ORDER-1")
        assert client.list_disputes(next_page_token="next-token")["items"] == []
        client.get_dispute("PP-D-1")
    creates = [r for r in calls if r.method == "POST" and r.url.path.endswith("/orders")]
    assert len(creates) == 2
    assert all(r.headers["PayPal-Request-Id"] == "logical-order-1" for r in creates)
    assert json.loads(creates[0].content) == {
        "intent": "CAPTURE", "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}]
    }
    captures = [r for r in calls if r.url.path.endswith("/capture")]
    assert len(captures) == 2
    assert captures[0].headers["PayPal-Request-Id"] == captures[1].headers["PayPal-Request-Id"]
    assert captures[0].method == "POST"
    assert json.loads(captures[0].content) == {}
    assert calls[-2].url.params["next_page_token"] == "next-token"
    assert calls[-2].url.path == "/v1/customer/disputes"
    assert calls[-1].url.path == "/v1/customer/disputes/PP-D-1"


@pytest.mark.parametrize("race", [False, True])
def test_completed_capture_is_noop_including_race(settings, race):
    calls = []

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return token()
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(422, json={"details": [{"issue": "ORDER_ALREADY_CAPTURED"}]})
        status = "APPROVED" if race and len(calls) == 1 else "COMPLETED"
        return httpx.Response(200, json={"id": "ORDER-1", "status": status})

    with PayPalClient(settings, transport=httpx.MockTransport(handler)) as client:
        assert client.capture_order("ORDER-1")["status"] == "COMPLETED"
    assert calls == (["GET", "POST", "GET"] if race else ["GET"])


@pytest.mark.parametrize("recover", [True, False])
def test_401_refreshes_once_and_preserves_idempotency_key(settings, recover):
    tokens, posts = [], []

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            tokens.append(request)
            return token(f"token-{len(tokens)}")
        posts.append(request)
        return httpx.Response(201 if recover and len(posts) == 2 else 401, json={"id": "ORDER-1"})

    with PayPalClient(settings, transport=httpx.MockTransport(handler)) as client:
        if recover:
            assert client.create_order("1.00", "USD", request_id="retry-1")["id"] == "ORDER-1"
        else:
            with pytest.raises(PayPalError, match="HTTP 401"):
                client.create_order("1.00", "USD", request_id="retry-1")
    assert len(tokens) == len(posts) == 2
    assert posts[0].headers["Authorization"] != posts[1].headers["Authorization"]
    assert all(r.headers["PayPal-Request-Id"] == "retry-1" for r in posts)


@pytest.mark.parametrize("status", [403, 404, 422, 429, 500])
def test_http_errors_are_safe_and_not_silently_retried(settings, status):
    calls = []

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return token()
        calls.append(request)
        return httpx.Response(status, json={"secret": "must-not-be-logged"})

    with PayPalClient(settings, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PayPalError) as error:
            client.get_dispute("PP-D-1")
    assert error.value.status_code == status
    assert "must-not-be-logged" not in str(error.value)
    assert len(calls) == 1


def test_timeout_is_sanitized(settings):
    def handler(request):
        raise httpx.ReadTimeout("sensitive-value", request=request)

    with PayPalClient(settings, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PayPalError, match="network request failed") as error:
            client.get_access_token()
    assert "sensitive-value" not in str(error.value)


def test_capture_timeout_retry_reuses_key_across_clients(settings):
    keys = []

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return token()
        if request.method == "GET":
            return httpx.Response(200, json={"status": "APPROVED"})
        keys.append(request.headers["PayPal-Request-Id"])
        if len(keys) == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(201, json={"status": "COMPLETED"})

    with PayPalClient(settings, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PayPalError):
            client.capture_order("ORDER-1")
    with PayPalClient(settings, transport=httpx.MockTransport(handler)) as client:
        assert client.capture_order("ORDER-1")["status"] == "COMPLETED"
    assert len(keys) == 2 and keys[0] == keys[1]


def test_unapproved_capture_error_is_not_treated_as_success(settings):
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return token()
        if request.method == "GET":
            return httpx.Response(200, json={"status": "CREATED"})
        return httpx.Response(422, json={"details": [{"issue": "ORDER_NOT_APPROVED"}]})

    with PayPalClient(settings, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PayPalError, match="HTTP 422"):
            client.capture_order("ORDER-1")


@pytest.mark.parametrize("data", [[], {}, {"access_token": "x", "expires_in": 0},
                                   {"access_token": "x", "expires_in": "bad"}])
def test_invalid_token_response(settings, data):
    with PayPalClient(settings, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=data)
    )) as client:
        with pytest.raises(PayPalError):
            client.get_access_token()


def test_non_json_response(settings):
    with PayPalClient(settings, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text="not-json")
    )) as client:
        with pytest.raises(PayPalError, match="invalid JSON"):
            client.get_access_token()


def test_validation_before_network(settings):
    def unexpected(_):
        pytest.fail("Invalid input must not send a request")

    with PayPalClient(settings, transport=httpx.MockTransport(unexpected)) as client:
        for resource_id in ("../bad", "x/y", "", "https://example.invalid"):
            with pytest.raises(ValueError):
                client.get_order(resource_id)
        for amount in ("0", "-1", "NaN", "1.234"):
            with pytest.raises(ValueError):
                client.create_order(amount, "USD", request_id="test")
        with pytest.raises(ValueError):
            client.create_order("1.00", "USD", request_id="")
        with pytest.raises(ValueError):
            client.list_disputes(page_size=51)
    with pytest.raises(ValueError):
        PayPalClient(settings.model_copy(update={"paypal_base_url": "https://example.invalid"}))
    with pytest.raises(ValueError, match="PAYPAL_CLIENT_ID"):
        PayPalClient(settings.model_copy(update={"paypal_client_id": ""}))
