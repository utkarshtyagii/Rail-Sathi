from decimal import Decimal, InvalidOperation
import re

from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, abort, flash, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from .extensions import db
from .models import ACTIVE_BOOKING_STATUSES, Booking, BookingStatusHistory, ServiceType, Station, SupportRequest, User, now_utc


bp = Blueprint("admin", __name__, url_prefix="/admin")


def require_admin():
    if current_user.role != "admin":
        abort(403)


def require_main_admin():
    require_admin()
    if not current_user.is_main_admin:
        abort(403)


@bp.post("/admins/create")
@login_required
def create_admin():
    require_main_admin()
    name = request.form.get("name", "").strip()
    submitted_email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    try:
        email = validate_email(submitted_email, check_deliverability=False).normalized
    except EmailNotValidError:
        email = ""

    if not 1 <= len(name) <= 120 or not email or len(email) > 255:
        flash("Enter a valid administrator name and email address.", "error")
    elif not 12 <= len(password) <= 128:
        flash("Use an administrator password between 12 and 128 characters.", "error")
    elif db.session.scalar(db.select(User).where(func.lower(User.email) == email.lower())):
        flash("An account already uses that email address.", "error")
    else:
        account = User(name=name, email=email, role="admin", active=True, is_main_admin=False)
        account.set_password(password)
        db.session.add(account)
        db.session.commit()
        flash(f"Administrator account created for {account.email}.", "success")
    return redirect(url_for("dashboards.admin_settings"))


@bp.post("/admins/<int:user_id>/status")
@login_required
def update_admin_status(user_id):
    require_main_admin()
    account = db.get_or_404(User, user_id)
    if account.role != "admin" or account.is_main_admin or account.id == current_user.id:
        abort(409)
    active = request.form.get("active")
    if active not in {"0", "1"}:
        abort(400)
    account.active = active == "1"
    db.session.commit()
    flash(f"{account.email} was {'activated' if account.active else 'deactivated'}.", "success")
    return redirect(url_for("dashboards.admin_settings"))


@bp.post("/porters/<int:user_id>/review")
@login_required
def review_porter(user_id):
    require_admin()
    porter = db.get_or_404(User, user_id)
    decision = request.form.get("decision")
    if decision not in {"verify", "reject"}:
        abort(400)
    decision = "verified" if decision == "verify" else "rejected"
    if porter.role != "porter" or porter.porter_status not in {"pending", "rejected"}:
        abort(409)
    if decision == "verified":
        phone_digits = "".join(character for character in (porter.phone or "") if character.isdigit())
        station_is_available = bool(porter.preferred_station and porter.preferred_station.supported)
        if not 8 <= len(phone_digits) <= 15 or not station_is_available:
            flash("The porter needs a valid phone number and an available preferred station before verification.", "error")
            return redirect(url_for("dashboards.admin_porters"))
    review_note = request.form.get("review_note", "").strip()[:300]
    if decision == "rejected" and not review_note:
        flash("Add a short reason so the applicant knows what to update.", "error")
        return redirect(url_for("dashboards.admin_porters"))
    porter.porter_status = decision
    porter.porter_available = decision == "verified"
    porter.porter_review_note = review_note or None
    db.session.commit()
    flash(f"{porter.name}'s porter application was {decision}.", "success")
    return redirect(url_for("dashboards.admin_porters"))


@bp.post("/bookings/<int:booking_id>/assign")
@login_required
def assign_booking(booking_id):
    require_admin()
    booking = db.get_or_404(Booking, booking_id)
    if booking.status not in {"requested", "declined"}:
        abort(409)
    porter = db.session.get(User, request.form.get("porter_id", type=int))
    if (
        not porter
        or porter.role != "porter"
        or porter.porter_status != "verified"
        or not porter.active
        or not porter.porter_available
        or porter.preferred_station_id != booking.station_id
        or Booking.query.filter_by(
            porter_id=porter.id,
            station_id=booking.station_id,
        ).filter(Booking.status.in_(ACTIVE_BOOKING_STATUSES)).first()
    ):
        flash("Choose an available, verified porter for this station.", "error")
        return redirect(url_for("dashboards.admin_bookings"))
    if booking.status == "declined" and porter.id == booking.porter_id:
        flash("Choose a different porter after an assignment is declined.", "error")
        return redirect(url_for("dashboards.admin_bookings"))
    previous_porter_name = booking.porter.name if booking.porter else None
    booking.porter_id = porter.id
    booking.status = "assigned"
    db.session.add(
        BookingStatusHistory(
            booking_id=booking.id,
            actor_id=current_user.id,
            status="assigned",
            note=(
                f"Reassigned from {previous_porter_name} to {porter.name}"
                if previous_porter_name
                else f"Assigned to {porter.name}; awaiting porter response"
            ),
        )
    )
    db.session.commit()
    flash(f"Booking {booking.public_id} assigned to {porter.name}; awaiting their response.", "success")
    return redirect(url_for("dashboards.admin_bookings"))


@bp.post("/stations/<int:station_id>/availability")
@login_required
def update_station_availability(station_id):
    require_admin()
    station = db.get_or_404(Station, station_id)
    supported = request.form.get("supported")
    if supported not in {"0", "1"}:
        abort(400)
    station.supported = supported == "1"
    db.session.commit()
    state = "available" if station.supported else "hidden from new bookings"
    flash(f"{station.name} is now {state}.", "success")
    return redirect(url_for("dashboards.admin_stations"))


@bp.post("/services/<int:service_id>/update")
@login_required
def update_service(service_id):
    require_admin()
    service = db.get_or_404(ServiceType, service_id)
    active = request.form.get("active")
    if active not in {"0", "1"}:
        abort(400)
    try:
        base_fare = Decimal(request.form.get("base_fare", ""))
    except (InvalidOperation, TypeError):
        base_fare = Decimal("-1")

    if not base_fare.is_finite() or not Decimal("1") <= base_fare <= Decimal("100000"):
        flash("Enter a service fare between ₹1 and ₹100,000.", "error")
        return redirect(url_for("dashboards.admin_pricing"))

    service.base_fare = base_fare.quantize(Decimal("0.01"))
    service.active = active == "1"
    db.session.commit()
    flash(f"{service.name} pricing and availability were updated.", "success")
    return redirect(url_for("dashboards.admin_pricing"))


@bp.post("/support-requests/<int:request_id>/status")
@login_required
def update_support_request(request_id):
    require_admin()
    support_request = db.get_or_404(SupportRequest, request_id)
    status = request.form.get("status")
    if status not in {"open", "closed"}:
        abort(400)
    if status == "closed" and support_request.status != "closed":
        support_request.closed_at = now_utc()
    elif status == "open":
        support_request.closed_at = None
    support_request.status = status
    db.session.commit()
    flash(f"Support request #{support_request.id} marked {status}.", "success")
    return redirect(url_for("dashboards.admin_support"))


@bp.post("/stations/create")
@login_required
def create_station():
    require_admin()
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip().upper()
    region = request.form.get("region", "").strip()
    if not name or len(name) > 120 or not region or len(region) > 80 or not re.fullmatch(r"[A-Z0-9]{2,10}", code):
        flash("Enter a station name, region, and code using 2–10 letters or numbers.", "error")
    elif Station.query.filter_by(code=code).first():
        flash(f"Station code {code} is already in use.", "error")
    else:
        db.session.add(Station(name=name, code=code, region=region, supported=True))
        db.session.commit()
        flash(f"{name} was added to station coverage.", "success")
    return redirect(url_for("dashboards.admin_stations"))


@bp.post("/stations/<int:station_id>/update")
@login_required
def update_station(station_id):
    require_admin()
    station = db.get_or_404(Station, station_id)
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip().upper()
    region = request.form.get("region", "").strip()
    duplicate = Station.query.filter(Station.code == code, Station.id != station.id).first()
    if not name or len(name) > 120 or not region or len(region) > 80 or not re.fullmatch(r"[A-Z0-9]{2,10}", code):
        flash("Enter a valid station name, region, and code.", "error")
    elif duplicate:
        flash(f"Station code {code} is already in use.", "error")
    else:
        station.name = name
        station.code = code
        station.region = region
        db.session.commit()
        flash(f"{station.name} details were updated.", "success")
    return redirect(url_for("dashboards.admin_stations"))
