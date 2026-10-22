"""Passenger checkout and Razorpay payment confirmation routes."""

import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from secrets import token_hex

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .extensions import csrf, db
from .models import Booking, PaymentAttempt
from .payment_provider import PaymentProviderError, create_order, fetch_payment, is_configured


bp = Blueprint("payments", __name__, url_prefix="/payments")
PROVIDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _passenger_booking(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if current_user.role != "passenger" or booking.passenger_id != current_user.id:
        abort(404)
    if booking.status != "completed":
        abort(409)
    return booking


def _owned_attempt(attempt_id):
    attempt = db.get_or_404(PaymentAttempt, attempt_id)
    if (
        current_user.role != "passenger"
        or attempt.booking.passenger_id != current_user.id
        or attempt.booking.status != "completed"
    ):
        abort(404)
    return attempt


@bp.post("/bookings/<int:booking_id>/checkout")
@login_required
def start_checkout(booking_id):
    booking = _passenger_booking(booking_id)
    if not is_configured():
        flash("Online payments are not configured yet. Please contact support to arrange payment.", "error")
        return redirect(url_for("dashboards.index"))

    attempts = PaymentAttempt.query.filter_by(booking_id=booking.id).order_by(PaymentAttempt.id.desc()).all()
    if any(attempt.status == "paid" for attempt in attempts):
        flash("This booking has already been paid.", "success")
        return redirect(url_for("dashboards.index"))

    active_attempt = next((attempt for attempt in attempts if attempt.status in {"creating", "created", "authorized", "processing"}), None)
    if active_attempt:
        if active_attempt.status == "creating":
            updated_at = active_attempt.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - updated_at > timedelta(minutes=5):
                active_attempt.status = "failed"
                db.session.commit()
                active_attempt = None
            else:
                flash("Your checkout is being prepared. Please refresh in a moment.", "success")
                return redirect(url_for("dashboards.index"))
    if active_attempt:
        if active_attempt.status in {"authorized", "processing"}:
            flash("Your payment is awaiting capture confirmation from the payment provider.", "success")
            return redirect(url_for("dashboards.index"))
        return redirect(url_for("payments.checkout", attempt_id=active_attempt.id))

    amount = Decimal(booking.estimated_fare)
    amount_paise = int(amount * 100)
    if amount <= 0 or amount * 100 != amount_paise:
        abort(409)

    attempt = PaymentAttempt(
        booking_id=booking.id,
        amount_paise=amount_paise,
        currency="INR",
        status="creating",
        receipt=f"rs{booking.id}{token_hex(8)}",
    )
    db.session.add(attempt)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        active_attempt = PaymentAttempt.query.filter_by(booking_id=booking.id).filter(
            PaymentAttempt.status.in_(["creating", "created", "authorized", "processing"])
        ).order_by(PaymentAttempt.id.desc()).first()
        if not active_attempt:
            raise
        if active_attempt.status == "created":
            return redirect(url_for("payments.checkout", attempt_id=active_attempt.id))
        flash("A payment attempt for this booking is already being processed.", "success")
        return redirect(url_for("dashboards.index"))

    try:
        order = create_order(
            amount_paise=attempt.amount_paise,
            receipt=attempt.receipt,
            booking_reference=booking.public_id,
        )
    except PaymentProviderError as error:
        attempt.status = "failed"
        db.session.commit()
        flash(str(error), "error")
        return redirect(url_for("dashboards.index"))

    if (
        not order.get("id")
        or order.get("amount") != attempt.amount_paise
        or order.get("currency") != attempt.currency
        or order.get("status") != "created"
    ):
        attempt.status = "failed"
        db.session.commit()
        flash("The payment provider returned an invalid order. Please try again or contact support.", "error")
        return redirect(url_for("dashboards.index"))

    attempt.provider_order_id = order["id"]
    attempt.status = "created"
    db.session.commit()
    return redirect(url_for("payments.checkout", attempt_id=attempt.id))


@bp.get("/attempts/<int:attempt_id>/checkout")
@login_required
def checkout(attempt_id):
    attempt = _owned_attempt(attempt_id)
    if attempt.status != "created" or not attempt.provider_order_id:
        return redirect(url_for("dashboards.index"))
    return render_template(
        "checkout.html",
        attempt=attempt,
        key_id=current_app.config["RAZORPAY_KEY_ID"],
    )


@bp.post("/attempts/<int:attempt_id>/verify")
@login_required
def verify_checkout(attempt_id):
    attempt = _owned_attempt(attempt_id)
    payload = request.get_json(silent=True) or {}
    order_id = payload.get("razorpay_order_id", "")
    payment_id = payload.get("razorpay_payment_id", "")
    signature = payload.get("razorpay_signature", "")

    if (
        not attempt.provider_order_id
        or order_id != attempt.provider_order_id
        or not PROVIDER_ID_PATTERN.fullmatch(payment_id)
        or not re.fullmatch(r"[a-fA-F0-9]{64}", signature)
    ):
        abort(400)

    secret = current_app.config.get("RAZORPAY_KEY_SECRET", "")
    signed_data = f"{attempt.provider_order_id}|{payment_id}".encode("utf-8")
    expected_signature = hmac.new(secret.encode("utf-8"), signed_data, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        abort(400)

    try:
        provider_payment = fetch_payment(payment_id)
    except PaymentProviderError as error:
        return jsonify(ok=False, message=str(error)), 503

    if (
        provider_payment.get("id") != payment_id
        or provider_payment.get("order_id") != attempt.provider_order_id
        or provider_payment.get("amount") != attempt.amount_paise
        or provider_payment.get("currency") != attempt.currency
    ):
        abort(400)

    attempt.provider_payment_id = payment_id
    if provider_payment.get("status") == "captured" and provider_payment.get("captured") is True:
        attempt.status = "paid"
        message = "Payment confirmed. Thank you."
    elif provider_payment.get("status") == "authorized":
        attempt.status = "authorized"
        message = "Payment authorization received. We are waiting for capture confirmation."
    elif provider_payment.get("status") == "failed":
        attempt.status = "failed"
        message = "The payment was not captured. You can start another checkout from your dashboard."
    else:
        attempt.status = "processing"
        message = "Razorpay is still processing your payment. Check your dashboard in a moment."
    db.session.commit()
    return jsonify(ok=attempt.status in {"paid", "authorized", "processing"}, status=attempt.status, message=message)


@bp.post("/webhook")
@csrf.exempt
def webhook():
    webhook_secret = current_app.config.get("RAZORPAY_WEBHOOK_SECRET", "")
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not webhook_secret or not signature:
        abort(400)

    raw_body = request.get_data(cache=True)
    expected = hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        abort(400)

    event = request.get_json(silent=True) or {}
    payload = event.get("payload") if isinstance(event, dict) else None
    payment_block = payload.get("payment") if isinstance(payload, dict) else None
    payment = payment_block.get("entity") if isinstance(payment_block, dict) else None
    payment = payment if isinstance(payment, dict) else {}
    event_name = event.get("event") if isinstance(event, dict) else None
    order_id = payment.get("order_id")
    if event_name not in {"payment.captured", "payment.failed"} or not order_id:
        return jsonify(ok=True, ignored=True)

    attempt = PaymentAttempt.query.filter_by(provider_order_id=order_id).first()
    if not attempt:
        return jsonify(ok=True, ignored=True)

    if payment.get("amount") != attempt.amount_paise or payment.get("currency") != attempt.currency:
        abort(400)
    if payment.get("id") and PROVIDER_ID_PATTERN.fullmatch(payment["id"]):
        attempt.provider_payment_id = payment["id"]

    if event_name == "payment.captured" and payment.get("captured") is True:
        attempt.status = "paid"
    elif event_name == "payment.failed" and attempt.status != "paid":
        attempt.status = "failed"
    db.session.commit()
    return jsonify(ok=True)
