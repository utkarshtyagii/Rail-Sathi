"""Consent based, booking scoped live location events."""

import math
from datetime import timedelta, timezone

from flask import current_app, request as socket_request
from flask_login import current_user
from flask_socketio import close_room, emit, join_room, rooms
from flask_wtf.csrf import validate_csrf
from sqlalchemy.exc import IntegrityError
from wtforms.validators import ValidationError

from .extensions import db, socketio
from .models import Booking, BookingLiveLocation, User, now_utc


TRACKING_STATUSES = {"assigned", "accepted", "en_route", "arrived", "in_progress"}
SHARING_STATUSES = {"accepted", "en_route", "arrived", "in_progress"}


def validate_location_payload(latitude, longitude, accuracy_m):
    """Return normalized GPS values, or None when any value is unsafe."""
    values = (latitude, longitude, accuracy_m)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        return None
    try:
        latitude, longitude, accuracy_m = (float(value) for value in values)
    except (OverflowError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (latitude, longitude, accuracy_m)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and 0 <= accuracy_m <= 100_000):
        return None
    return latitude, longitude, accuracy_m


def participant_room(booking_id, user_id):
    return f"booking-tracking:{booking_id}:user:{user_id}"


def _payload_dict(payload):
    return payload if isinstance(payload, dict) else {}


def _csrf_is_valid(payload):
    if not current_app.config.get("WTF_CSRF_ENABLED", True):
        return True
    token = payload.get("csrfToken")
    if not isinstance(token, str):
        return False
    try:
        validate_csrf(token)
    except (ValidationError, TypeError):
        return False
    return True


def _find_authorized_booking(payload):
    if not current_user.is_authenticated:
        return None, None, "unauthenticated"
    booking_id = payload.get("bookingId")
    if isinstance(booking_id, bool) or not isinstance(booking_id, int):
        return None, None, "booking_unavailable"
    booking = db.session.get(Booking, booking_id)
    if not booking or booking.status not in TRACKING_STATUSES:
        return None, None, "booking_unavailable"

    passenger = db.session.get(User, booking.passenger_id)
    porter = db.session.get(User, booking.porter_id) if booking.porter_id else None
    if (
        not passenger or passenger.role != "passenger" or not passenger.active
        or not porter or porter.role != "porter" or not porter.active
        or porter.porter_status != "verified"
    ):
        return None, None, "booking_unavailable"

    if current_user.role == "passenger" and booking.passenger_id == current_user.id:
        return booking, "passenger", None
    if (
        current_user.role == "porter"
        and current_user.porter_status == "verified"
        and booking.porter_id == current_user.id
    ):
        return booking, "porter", None
    return None, None, "booking_unavailable"


def _normalized_timestamp(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_location(location, role):
    if not location or not location.is_sharing or location.latitude is None or location.longitude is None:
        return None
    return {
        "role": role,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "accuracyM": location.accuracy_m,
        "updatedAt": _normalized_timestamp(location.updated_at).isoformat(),
    }


def _booking_locations(booking):
    participants = {booking.passenger_id: "passenger", booking.porter_id: "porter"}
    locations = BookingLiveLocation.query.filter(
        BookingLiveLocation.booking_id == booking.id,
        BookingLiveLocation.user_id.in_(participants),
        BookingLiveLocation.is_sharing.is_(True),
    ).all()
    latest = {participants[item.user_id]: _serialize_location(item, participants[item.user_id]) for item in locations}
    return {role: data for role, data in latest.items() if data}


def _emit_to_participants(event, payload, booking):
    for user_id in {booking.passenger_id, booking.porter_id}:
        if user_id:
            socketio.emit(event, payload, to=participant_room(booking.id, user_id))


def close_booking_tracking(booking_id):
    """Clear saved fixes and close participant rooms after a terminal transition."""
    booking = db.session.get(Booking, booking_id)
    BookingLiveLocation.query.filter_by(booking_id=booking_id).delete(synchronize_session=False)
    db.session.commit()
    if booking:
        _emit_to_participants("tracking:closed", {"bookingId": booking.id}, booking)
        for user_id in {booking.passenger_id, booking.porter_id}:
            if user_id:
                close_room(participant_room(booking.id, user_id), namespace="/")


@socketio.on("tracking:join")
def join_tracking(payload):
    payload = _payload_dict(payload)
    if not _csrf_is_valid(payload):
        return {"ok": False, "code": "csrf_invalid", "message": "Refresh this page before joining tracking."}
    booking, role, error = _find_authorized_booking(payload)
    if error:
        return {"ok": False, "code": error, "message": "Tracking is only available to the passenger and assigned porter on an active job."}

    room = participant_room(booking.id, current_user.id)
    join_room(room)
    location = BookingLiveLocation.query.filter_by(booking_id=booking.id, user_id=current_user.id).first()
    if not location:
        interval = max(1, int(current_app.config.get("LOCATION_UPDATE_MIN_INTERVAL_SECONDS", 3)))
        location = BookingLiveLocation(
            booking_id=booking.id,
            user_id=current_user.id,
            updated_at=now_utc() - timedelta(seconds=interval + 1),
        )
        db.session.add(location)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            location = BookingLiveLocation.query.filter_by(booking_id=booking.id, user_id=current_user.id).first()
            if not location:
                return {"ok": False, "code": "tracking_unavailable", "message": "Tracking could not be started. Please retry."}

    emit(
        "tracking:state",
        {
            "bookingId": booking.id,
            "pickup": {
                "label": booking.pickup,
                "latitude": booking.pickup_latitude,
                "longitude": booking.pickup_longitude,
            },
            "destination": {
                "label": booking.destination,
                "latitude": booking.destination_latitude,
                "longitude": booking.destination_longitude,
            },
            "status": booking.status,
            "sharingOptedOut": bool(location.sharing_opted_out),
            "locations": _booking_locations(booking),
            "staleAfterSeconds": max(5, int(current_app.config.get("LOCATION_STALE_AFTER_SECONDS", 30))),
        },
        to=socket_request.sid,
    )
    return {"ok": True, "bookingId": booking.id, "role": role, "sharingOptedOut": bool(location.sharing_opted_out)}


@socketio.on("tracking:location:update")
def update_tracking_location(payload):
    payload = _payload_dict(payload)
    if not _csrf_is_valid(payload):
        return {"ok": False, "code": "csrf_invalid", "message": "Refresh this page before sharing location."}
    booking, role, error = _find_authorized_booking(payload)
    if error:
        return {"ok": False, "code": error, "message": "This booking is no longer available for location sharing."}
    if booking.status not in SHARING_STATUSES:
        return {"ok": False, "code": "booking_not_accepted", "message": "Location sharing starts after the porter accepts this booking."}
    room = participant_room(booking.id, current_user.id)
    if room not in rooms(sid=socket_request.sid):
        return {"ok": False, "code": "join_required", "message": "Join this booking's tracking session before sharing."}

    coordinates = validate_location_payload(
        payload.get("latitude"), payload.get("longitude"), payload.get("accuracyM")
    )
    if not coordinates:
        return {"ok": False, "code": "invalid_coordinates", "message": "The GPS update did not contain valid coordinates."}

    now = now_utc()
    location = BookingLiveLocation.query.filter_by(booking_id=booking.id, user_id=current_user.id).first()
    if location:
        elapsed = (now - _normalized_timestamp(location.updated_at)).total_seconds()
        interval = max(1, int(current_app.config.get("LOCATION_UPDATE_MIN_INTERVAL_SECONDS", 3)))
        if elapsed < interval:
            return {
                "ok": False,
                "code": "rate_limited",
                "retryAfterSeconds": round(interval - elapsed, 1),
                "message": "Location updates are arriving too quickly. The latest valid fix is kept.",
            }
    else:
        location = BookingLiveLocation(booking_id=booking.id, user_id=current_user.id)
        db.session.add(location)

    latitude, longitude, accuracy_m = coordinates
    location.latitude = latitude
    location.longitude = longitude
    location.accuracy_m = accuracy_m
    location.is_sharing = True
    location.sharing_opted_out = False
    location.updated_at = now
    db.session.commit()

    update = {
        "bookingId": booking.id,
        "role": role,
        "latitude": latitude,
        "longitude": longitude,
        "accuracyM": accuracy_m,
        "updatedAt": now.isoformat(),
    }
    _emit_to_participants("tracking:location", update, booking)
    return {"ok": True, "updatedAt": update["updatedAt"]}


@socketio.on("tracking:stop")
def stop_tracking(payload):
    payload = _payload_dict(payload)
    if not _csrf_is_valid(payload):
        return {"ok": False, "code": "csrf_invalid", "message": "Refresh this page before stopping sharing."}
    booking, role, error = _find_authorized_booking(payload)
    if error:
        return {"ok": False, "code": error, "message": "Tracking for this booking has ended."}
    room = participant_room(booking.id, current_user.id)
    if room not in rooms(sid=socket_request.sid):
        return {"ok": False, "code": "join_required", "message": "Join this booking's tracking session first."}

    location = BookingLiveLocation.query.filter_by(booking_id=booking.id, user_id=current_user.id).first()
    if location:
        location.latitude = None
        location.longitude = None
        location.accuracy_m = None
        location.is_sharing = False
        location.sharing_opted_out = True
        db.session.commit()
    _emit_to_participants(
        "tracking:participant_stopped",
        {"bookingId": booking.id, "role": role},
        booking,
    )
    return {"ok": True}


@socketio.on("tracking:resume")
def resume_tracking(payload):
    payload = _payload_dict(payload)
    if not _csrf_is_valid(payload):
        return {"ok": False, "code": "csrf_invalid", "message": "Refresh this page before resuming sharing."}
    booking, _role, error = _find_authorized_booking(payload)
    if error or booking.status not in SHARING_STATUSES:
        return {"ok": False, "code": error or "booking_not_accepted", "message": "Sharing can resume only for your accepted active booking."}
    room = participant_room(booking.id, current_user.id)
    if room not in rooms(sid=socket_request.sid):
        return {"ok": False, "code": "join_required", "message": "Join this booking's tracking session first."}
    location = BookingLiveLocation.query.filter_by(booking_id=booking.id, user_id=current_user.id).first()
    if location:
        location.sharing_opted_out = False
        db.session.commit()
    return {"ok": True}


@socketio.on("tracking:pause")
def pause_tracking(payload):
    """Clear the latest fix when browser consent is withdrawn or GPS fails permission."""
    payload = _payload_dict(payload)
    if not _csrf_is_valid(payload):
        return {"ok": False, "code": "csrf_invalid", "message": "Refresh this page before pausing sharing."}
    booking, role, error = _find_authorized_booking(payload)
    if error:
        return {"ok": False, "code": error, "message": "This booking is no longer available for location sharing."}
    room = participant_room(booking.id, current_user.id)
    if room not in rooms(sid=socket_request.sid):
        return {"ok": False, "code": "join_required", "message": "Join this booking's tracking session first."}
    location = BookingLiveLocation.query.filter_by(booking_id=booking.id, user_id=current_user.id).first()
    if location:
        location.latitude = location.longitude = location.accuracy_m = None
        location.is_sharing = False
        db.session.commit()
    _emit_to_participants("tracking:participant_stopped", {"bookingId": booking.id, "role": role}, booking)
    return {"ok": True}
