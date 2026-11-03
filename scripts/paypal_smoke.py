"""T1.2 acceptance check: create an unapproved Sandbox order, then list disputes."""

import argparse
from pathlib import Path
import sys
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings
from app.services.paypal import PayPalClient, PayPalError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", default=str(uuid4()),
                        help="Reuse this ID when retrying the same smoke order")
    args = parser.parse_args()
    print(f"Sandbox smoke request ID: {args.request_id}", flush=True)
    try:
        settings = Settings()
    except ValueError:
        print("FAIL: invalid environment settings; check the root .env", file=sys.stderr)
        return 1
    try:
        with PayPalClient(settings) as paypal:
            order = paypal.create_order("1.00", "USD", request_id=args.request_id)
            approval = next((link.get("href") for link in order.get("links", [])
                             if link.get("rel") in ("approve", "payer-action")), None)
            if not isinstance(approval, str):
                raise PayPalError("Order response has no approval link")
            url = urlparse(approval)
            if url.scheme != "https" or url.hostname != "www.sandbox.paypal.com":
                raise PayPalError("Order response has an unexpected approval link host")
            print(f"Sandbox approval link: {approval}", flush=True)
            disputes = paypal.list_disputes()
            if not isinstance(disputes.get("items"), list):
                raise PayPalError("Disputes response has no items list")
            print(f"List disputes: OK ({len(disputes['items'])} items on first page)")
            print("PASS: Sandbox order created and disputes listed. No payment captured.")
    except (PayPalError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
