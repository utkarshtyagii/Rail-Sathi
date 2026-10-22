from datetime import datetime
from decimal import Decimal
import math
from secrets import token_urlsafe
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .handoff import issue_handoff_code, verify_handoff_code
from .models import ACTIVE_BOOKING_STATUSES, Booking, BookingStatusHistory, PorterReview, ServiceType, Station, User


bp = Blueprint("bookings", __name__)
INDIA_TIME = ZoneInfo("Asia/Kolkata")

TRANSITIONS = {
    "requested": {"accepted", "cancelled"},
    "assigned": {"accepted", "declined", "cancelled"},
    "declined": {"cancelled"},
    "accepted": {"en_route"},
    "en_route": {"arrived"},
    "arrived": {"in_progress"},
    "in_progress": {"completed"},
}


def create_public_id():
    while True:
        public_id = token_urlsafe(9).replace("-", "").replace("_", "")[:12].upper()
        if not Booking.query.filter_by(public_id=public_id).first():
            return public_id


def _read_optional_coordinate_pair(form, prefix):
    latitude_text = form.get(f"{prefix}_latitude", "").strip()
    longitude_text = form.get(f"{prefix}_longitude", "").strip()
    if not latitude_text and not longitude_text:
        return None, None, False
    try:
        latitude, longitude = float(latitude_text), float(longitude_text)
        valid = math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180
    except ValueError:
        valid = False
        latitude = longitude = None
    return (latitude, longitude, False) if valid else (None, None, True)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if current_user.role != "passenger":
        abort(403)

    stations = Station.query.filter_by(supported=True).order_by(Station.name).all()
    services = ServiceType.query.filter_by(active=True).order_by(ServiceType.name).all()
    selected_station = request.values.get("station", type=int)
    selected_service = request.values.get("service", type=int)
    if request.method == "POST":
        station = db.session.get(Station, request.form.get("station", type=int))
        service = db.session.get(ServiceType, request.form.get("service", type=int))
        pickup = request.form.get("pickup", "").strip()
        destination = request.form.get("destination", "").strip()
        passenger_phone = request.form.get("passenger_phone", "").strip()
        phone_digits = "".join(character for character in passenger_phone if character.isdigit())

        pickup_latitude, pickup_longitude, pickup_coordinates_invalid = _read_optional_coordinate_pair(request.form, "pickup")
        destination_latitude, destination_longitude, destination_coordinates_invalid = _read_optional_coordinate_pair(request.form, "destination")

        try:
            service_date = request.form.get("service_date", "").strip()
            service_time = request.form.get("service_time", "").strip()
            service_at = datetime.fromisoformat(f"{service_date}T{service_time}")
            if service_at.tzinfo is None:
                service_at = service_at.replace(tzinfo=INDIA_TIME)
            else:
                service_at = service_at.astimezone(INDIA_TIME)
            bags = int(request.form.get("bags", 1))
        except (TypeError, ValueError):
            service_at = None
            bags = 0

        if (
            not station
            or not station.supported
            or not service
            or not service.active
            or service.station_id != station.id
            or not pickup
            or not destination
            or pickup_coordinates_invalid
            or destination_coordinates_invalid
            or len(passenger_phone) > 30
            or not all(character.isdigit() or character in "+().- " for character in passenger_phone)
            or not 8 <= len(phone_digits) <= 15
            or not 1 <= bags <= 20
        ):
            flash(
                "The pickup map pin is invalid. Choose your current location again or clear it before continuing."
                if pickup_coordinates_invalid or destination_coordinates_invalid
                else "Choose a supported station and service, and complete the required journey details.",
                "error",
            )
        elif not service_at or service_at <= datetime.now(INDIA_TIME):
            flash("Choose a future service date and time.", "error")
        else:
            base_fare = Decimal(service.base_fare)
            luggage_fare = Decimal(max(0, bags - 1) * 35)
            estimated_fare = base_fare + luggage_fare

            booking = Booking(
                public_id=create_public_id(),
                passenger_id=current_user.id,
                station_id=station.id,
                service_id=service.id,
                service_at=service_at,
                passenger_phone=passenger_phone,
                train_number=request.form.get("train_number", "").strip()[:20],
                platform=request.form.get("platform", "").strip()[:20],
                coach=request.form.get("coach", "").strip()[:20],
                berth=request.form.get("berth", "").strip()[:20],
                pickup=pickup[:180],
                pickup_latitude=pickup_latitude,
                pickup_longitude=pickup_longitude,
                destination=destination[:180],
                destination_latitude=destination_latitude,
                destination_longitude=destination_longitude,
                bags=bags,
                instructions=request.form.get("instructions", "").strip()[:500],
                estimated_fare=estimated_fare,
            )
            db.session.add(booking)
            db.session.flush()
            db.session.add(
                BookingStatusHistory(
                    booking_id=booking.id,
                    actor_id=current_user.id,
                    status="requested",
                    note="Booking created",
                )
            )
            db.session.commit()
            flash(f"Booking {booking.public_id} created. Payment is not collected in this version.", "success")
            return redirect(url_for("dashboards.passenger_bookings", q=booking.public_id))

    return render_template(
        "booking_new.html",
        stations=stations,
        services=services,
        selected_station=selected_station,
        selected_service=selected_service,
    )


@bp.post("/<int:booking_id>/status")
@login_required
def update_status(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    new_status = request.form.get("status", "")
    previous_status = booking.status
    claim_open_request = False
    porter_accepting = current_user.role == "porter" and new_status == "accepted"
    resulting_status = "en_route" if porter_accepting else new_status

    if current_user.role == "passenger":
        allowed = (
            booking.passenger_id == current_user.id
            and booking.status in {"requested", "assigned", "declined"}
            and new_status == "cancelled"
        )
    elif current_user.role == "porter":
        claim_open_request = (
            booking.status == "requested"
            and booking.porter_id is None
            and new_status == "accepted"
        )
        if claim_open_request:
            allowed = (
                current_user.porter_status == "verified"
                and current_user.active
                and current_user.porter_available
                and current_user.preferred_station_id == booking.station_id
            )
        else:
            allowed = (
                current_user.porter_status == "verified"
                and booking.porter_id == current_user.id
                and new_status in {"accepted", "declined", "en_route", "arrived", "in_progress", "completed"}
            )
    else:
        allowed = False

    if not allowed or new_status not in TRANSITIONS.get(previous_status, set()):
        abort(403)

    if new_status in {"in_progress", "completed"}:
        code_is_valid, code_error = verify_handoff_code(booking, request.form.get("handoff_otp"))
        if not code_is_valid:
            db.session.commit()
            action = "complete the job" if new_status == "completed" else "start assistance"
            if code_error == "invalid":
                message = "That handoff code does not match. Confirm the current six-digit code with the passenger."
            elif code_error in {"expired", "locked"}:
                message = f"The code has expired or reached its attempt limit. Ask the passenger to generate a new code to {action}."
            elif code_error == "not_issued":
                message = f"Ask the passenger to generate a confirmation code from their booking page to {action}."
            else:
                message = f"Enter the passenger’s six-digit confirmation code to {action}."
            flash(message, "error")
            return redirect(url_for("dashboards.index"))

    if new_status in {"arrived", "in_progress"}:
        issue_handoff_code(booking)

    if claim_open_request:
        # Serialize claims per porter where the database supports row locks, then
        # conditionally claim the request so only one station porter can win it.
        porter = db.session.execute(
            db.select(User).where(User.id == current_user.id).with_for_update()
        ).scalar_one()
        if (
            porter.role != "porter"
            or porter.porter_status != "verified"
            or not porter.active
            or not porter.porter_available
            or porter.preferred_station_id != booking.station_id
        ):
            abort(403)
        existing_job = Booking.query.filter(
            Booking.porter_id == porter.id,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        ).first()
        if existing_job:
            abort(409)
        claimed = Booking.query.filter(
            Booking.id == booking.id,
            Booking.status == "requested",
            Booking.porter_id.is_(None),
            Booking.station_id == porter.preferred_station_id,
        ).update(
            {"porter_id": porter.id, "status": resulting_status},
            synchronize_session=False,
        )
        if claimed != 1:
            db.session.rollback()
            abort(409)
        booking.porter_id = porter.id
        booking.status = resulting_status
    else:
        booking.status = resulting_status
    db.session.add(
        BookingStatusHistory(
            booking_id=booking.id,
            actor_id=current_user.id,
            status=new_status,
        )
    )
    if porter_accepting:
        db.session.add(
            BookingStatusHistory(
                booking_id=booking.id,
                actor_id=current_user.id,
                status="en_route",
                note="Trip started after porter accepted the booking",
            )
        )
    db.session.commit()
    if porter_accepting:
        from .tracking import _emit_to_participants

        _emit_to_participants(
            "tracking:booking_active",
            {"bookingId": booking.id, "status": booking.status},
            booking,
        )
    if new_status in {"completed", "declined", "cancelled"}:
        from .tracking import close_booking_tracking

        close_booking_tracking(booking.id)
    flash(
        f"Booking {booking.public_id} accepted. Head to the pickup point and mark arrival from your dashboard."
        if porter_accepting
        else (
            "The porter has completed the job. Please rate your porter from My bookings."
            if new_status == "completed"
            else f"Booking {booking.public_id} updated to {new_status.replace('_', ' ')}."
        ),
        "success",
    )
    if current_user.role == "passenger":
        return redirect(url_for("dashboards.passenger_bookings"))
    if new_status in {"completed", "declined", "cancelled"}:
        return redirect(url_for("dashboards.porter_history"))
    if porter_accepting:
        return redirect(url_for("dashboards.index"))
    return redirect(url_for("dashboards.porter_active_job"))


@bp.post("/<int:booking_id>/handoff-otp/regenerate")
@login_required
def regenerate_handoff_otp(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if (
        current_user.role != "passenger"
        or booking.passenger_id != current_user.id
        or booking.status not in {"arrived", "in_progress"}
    ):
        abort(403)
    issue_handoff_code(booking)
    db.session.commit()
    purpose = "confirm completion" if booking.status == "in_progress" else "start assistance"
    flash(f"A new confirmation code is ready. Share it with your porter to {purpose}.", "success")
    return redirect(url_for("dashboards.passenger_bookings", status="active", q=booking.public_id))


@bp.post("/<int:booking_id>/review")
@login_required
def submit_porter_review(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if (
        current_user.role != "passenger"
        or booking.passenger_id != current_user.id
        or booking.status != "completed"
        or booking.porter_id is None
    ):
        abort(403)
    if PorterReview.query.filter_by(booking_id=booking.id).first():
        flash("You have already rated this completed booking.", "error")
        return redirect(url_for("dashboards.passenger_bookings", status="completed", q=booking.public_id))

    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()
    if rating not in {1, 2, 3, 4, 5} or len(comment) > 500:
        flash("Choose a rating from one to five stars. Feedback can be up to 500 characters.", "error")
        return redirect(url_for("dashboards.passenger_bookings", status="completed", q=booking.public_id))

    db.session.add(PorterReview(
        booking_id=booking.id,
        passenger_id=current_user.id,
        porter_id=booking.porter_id,
        rating=rating,
        comment=comment or None,
    ))
    db.session.commit()
    flash("Thank you for rating your porter.", "success")
    return redirect(url_for("dashboards.passenger_bookings", status="completed", q=booking.public_id))
