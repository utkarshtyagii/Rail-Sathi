"""Small server-side client for the Razorpay Orders and Payments APIs."""

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


class PaymentProviderError(Exception):
    """Raised when Razorpay is not configured or rejects a request."""


def is_configured():
    return bool(
        current_app.config.get("RAZORPAY_KEY_ID")
        and current_app.config.get("RAZORPAY_KEY_SECRET")
        and current_app.config.get("RAZORPAY_WEBHOOK_SECRET")
    )


def _request(path, *, payload=None):
    if not is_configured():
        raise PaymentProviderError("Online payments are not configured yet.")

    key_id = current_app.config["RAZORPAY_KEY_ID"]
    key_secret = current_app.config["RAZORPAY_KEY_SECRET"]
    token = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"https://api.razorpay.com/v1/{path.lstrip('/')}",
        data=body,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )

    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        raise PaymentProviderError("Razorpay could not complete the request. Please try again.") from error

    if not isinstance(result, dict):
        raise PaymentProviderError("Razorpay returned an unexpected response.")
    return result


def create_order(*, amount_paise, receipt, booking_reference):
    return _request(
        "orders",
        payload={
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": {"booking_reference": booking_reference},
        },
    )


def fetch_payment(payment_id):
    return _request(f"payments/{payment_id}")
