"""Passenger handoff-code helpers for starting a porter job."""

import hashlib
import hmac
import re
import secrets
from datetime import timedelta, timezone

from flask import current_app
from flask_login import current_user

from .models import now_utc


HANDOFF_CODE_TTL_MINUTES = 15
HANDOFF_CODE_MAX_ATTEMPTS = 5


def _utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def issue_handoff_code(booking):
    """Create a passenger-visible code without storing the code itself."""
    booking.handoff_otp_nonce = secrets.token_urlsafe(24)
    booking.handoff_otp_expires_at = now_utc() + timedelta(minutes=HANDOFF_CODE_TTL_MINUTES)
    booking.handoff_otp_attempts = 0
    booking.handoff_otp_verified_at = None


def _code_for_nonce(booking):
    secret = str(current_app.config["SECRET_KEY"]).encode("utf-8")
    message = f"rail-sathi-handoff:{booking.id}:{booking.handoff_otp_nonce}".encode("utf-8")
    digest = hmac.new(secret, message, hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def _code_is_active(booking):
    return bool(
        booking.status in {"arrived", "in_progress"}
        and booking.handoff_otp_nonce
        and booking.handoff_otp_expires_at
        and not booking.handoff_otp_verified_at
        and (booking.handoff_otp_attempts or 0) < HANDOFF_CODE_MAX_ATTEMPTS
        and _utc(booking.handoff_otp_expires_at) > now_utc()
    )


def passenger_handoff_code(booking):
    """Return an active code only to the passenger who owns this booking."""
    if (
        not current_user.is_authenticated
        or current_user.role != "passenger"
        or booking.passenger_id != current_user.id
        or not _code_is_active(booking)
    ):
        return None
    return _code_for_nonce(booking)


def verify_handoff_code(booking, submitted_code):
    """Validate a passenger's code and record attempts or successful use."""
    if not booking.handoff_otp_nonce or not booking.handoff_otp_expires_at:
        return False, "not_issued"
    if _utc(booking.handoff_otp_expires_at) <= now_utc():
        return False, "expired"
    if (booking.handoff_otp_attempts or 0) >= HANDOFF_CODE_MAX_ATTEMPTS:
        return False, "locked"

    code = (submitted_code or "").strip()
    if not re.fullmatch(r"[0-9]{6}", code):
        if code:
            booking.handoff_otp_attempts = (booking.handoff_otp_attempts or 0) + 1
        return False, "invalid"

    if not hmac.compare_digest(_code_for_nonce(booking), code):
        booking.handoff_otp_attempts = (booking.handoff_otp_attempts or 0) + 1
        return False, "invalid"

    booking.handoff_otp_verified_at = now_utc()
    return True, None
