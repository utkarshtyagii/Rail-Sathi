import csv
from io import StringIO
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, selectinload
from .extensions import db
from .models import ACTIVE_BOOKING_STATUSES, Booking, BookingStatusHistory, PaymentAttempt, PorterReview, ServiceType, Station, SupportRequest, User, now_utc

bp = Blueprint("dashboards", __name__)
INDIA_TIME = ZoneInfo("Asia/Kolkata")


def _passenger_bookings(user_id):
    return Booking.query.options(
        joinedload(Booking.station),
        joinedload(Booking.service),
        joinedload(Booking.porter),
        selectinload(Booking.history),
        selectinload(Booking.payments),
    ).filter_by(passenger_id=user_id).order_by(Booking.created_at.desc()).all()


def _porter_bookings(user_id):
    return Booking.query.options(
        joinedload(Booking.station),
        joinedload(Booking.service),
        joinedload(Booking.passenger),
        selectinload(Booking.history),
    ).filter_by(porter_id=user_id).order_by(Booking.service_at.asc()).all()


def _open_station_bookings(station_id):
    if not station_id:
        return []
    return Booking.query.options(
        joinedload(Booking.station),
        joinedload(Booking.service),
        joinedload(Booking.passenger),
        selectinload(Booking.history),
    ).filter(
        Booking.station_id == station_id,
        Booking.status == "requested",
        Booking.porter_id.is_(None),
    ).order_by(Booking.service_at.asc()).all()


def _booking_service_date(booking):
    service_at = booking.service_at
    if service_at.tzinfo is None:
        service_at = service_at.replace(tzinfo=INDIA_TIME)
    else:
        service_at = service_at.astimezone(INDIA_TIME)
    return service_at.date()


def _require_admin():
    if current_user.role != "admin":
        abort(403)


def _admin_bookings(limit=None):
    query = Booking.query.options(
        joinedload(Booking.station), joinedload(Booking.service),
        joinedload(Booking.passenger), joinedload(Booking.porter),
        selectinload(Booking.payments),
    ).order_by(Booking.created_at.desc())
    return query.limit(limit).all() if limit else query.all()


def _admin_dashboard_data():
    today = datetime.now(INDIA_TIME).date()
    booking_count = Booking.query.count()
    passengers_count = User.query.filter_by(role="passenger").count()
    porters_count = User.query.filter_by(role="porter", porter_status="verified", active=True).count()
    pending_porters = User.query.options(joinedload(User.preferred_station)).filter_by(
        role="porter", porter_status="pending"
    ).order_by(User.created_at.asc()).limit(8).all()
    open_tickets = SupportRequest.query.filter_by(status="open").count()
    active_count = Booking.query.filter(Booking.status.in_(ACTIVE_BOOKING_STATUSES)).count()
    all_bookings = _admin_bookings()
    completed_today = [b for b in all_bookings if b.status == "completed" and _booking_service_date(b) == today]
    gross_estimates = db.session.query(db.func.coalesce(db.func.sum(Booking.estimated_fare), 0)).scalar() or 0
    recent_bookings = all_bookings[:6]
    day_labels = []
    day_values = []
    for offset in range(6, -1, -1):
        day = today.fromordinal(today.toordinal() - offset)
        day_labels.append(day.strftime("%a"))
        day_values.append(sum(1 for booking in all_bookings if (booking.created_at.replace(tzinfo=INDIA_TIME) if booking.created_at.tzinfo is None else booking.created_at.astimezone(INDIA_TIME)).date() == day))
    pending_assignment = Booking.query.filter(Booking.status.in_(("requested", "declined"))).count()
    status_counts = {
        "completed": Booking.query.filter_by(status="completed").count(),
        "active": active_count,
        "needs_assignment": pending_assignment,
        "cancelled": Booking.query.filter_by(status="cancelled").count(),
    }
    total_status = booking_count
    return {
        "today_label": datetime.now(INDIA_TIME).strftime("%d %B %Y"),
        "passengers_count": passengers_count,
        "porters_count": porters_count,
        "pending_verification_count": User.query.filter_by(role="porter", porter_status="pending").count(),
        "booking_count": booking_count,
        "active_count": active_count,
        "completed_today_count": len(completed_today),
        "gross_estimates": gross_estimates,
        "open_tickets": open_tickets,
        "recent_bookings": recent_bookings,
        "pending_porters": pending_porters,
        "weekly_labels": day_labels,
        "weekly_values": day_values,
        "status_counts": status_counts,
        "status_total": total_status,
        "verified_porters": porters_count,
    }


@bp.get("/")
@login_required
def index():
    if current_user.role == "admin":
        return render_template("admin/dashboard.html", **_admin_dashboard_data())

    pending_porters = []
    verified_porters = []
    porter_stations = []
    catalog_stations = []
    support_requests = []
    open_support_count = 0
    admin_accounts = []
    busy_porter_ids = set()
    porter_available = False
    porter_active_bookings = []
    porter_completed_count = 0
    porter_pending_request_count = 0
    porter_today_earnings = Decimal("0.00")
    porter_today_job_count = 0
    porter_average_rating = None
    porter_rating_count = 0
    porter_on_active_job = False
    passenger_open_bookings = []
    passenger_completed_count = 0
    active_booking_count = 0
    booking_query = Booking.query.options(
        joinedload(Booking.station),
        joinedload(Booking.service),
        joinedload(Booking.porter),
        selectinload(Booking.history),
        selectinload(Booking.payments),
    )


    if current_user.role == "porter":
        porter_stations = Station.query.filter_by(supported=True).order_by(Station.name).all()
    if current_user.role == "admin":
        bookings = booking_query.order_by(Booking.created_at.desc()).limit(100).all()
        catalog_stations = Station.query.options(selectinload(Station.services)).order_by(Station.name).all()
        support_requests = SupportRequest.query.order_by(
            SupportRequest.status.desc(), SupportRequest.created_at.desc()
        ).limit(100).all()
        open_support_count = SupportRequest.query.filter_by(status="open").count()
        pending_porters = User.query.filter_by(role="porter", porter_status="pending").filter(
            User.phone.isnot(None), User.preferred_station_id.isnot(None)
        ).order_by(User.created_at.asc()).all()
        verified_porters = User.query.filter_by(role="porter", porter_status="verified", active=True).order_by(User.name.asc()).all()
        busy_porter_ids = set(
            db.session.scalars(
                db.select(Booking.porter_id).where(
                    Booking.porter_id.isnot(None),
                    Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                )
            ).all()
        )
        if current_user.is_main_admin:
            admin_accounts = User.query.filter_by(role="admin", is_main_admin=False).order_by(User.name.asc()).all()
    elif current_user.role == "porter":
        if current_user.porter_status == "verified":
            bookings = booking_query.filter(
                Booking.porter_id == current_user.id,
                Booking.status.notin_(["declined", "cancelled"]),
            ).order_by(Booking.created_at.desc()).all()
            porter_active_bookings = sorted(
                (booking for booking in bookings if booking.status in ACTIVE_BOOKING_STATUSES),
                key=lambda booking: booking.service_at,
            )
            porter_completed_count = sum(booking.status == "completed" for booking in bookings)
            porter_reviews = PorterReview.query.filter_by(porter_id=current_user.id).all()
            porter_rating_count = len(porter_reviews)
            porter_average_rating = (
                sum(review.rating for review in porter_reviews) / porter_rating_count
                if porter_rating_count else None
            )
            today = datetime.now(INDIA_TIME).date()
            completed_today = [
                booking for booking in bookings
                if booking.status == "completed" and _booking_service_date(booking) == today
            ]
            porter_today_earnings = sum(
                (booking.estimated_fare or Decimal("0.00") for booking in completed_today),
                Decimal("0.00"),
            )
            porter_today_job_count = len(completed_today)
            porter_pending_request_count = sum(booking.status == "assigned" for booking in bookings)
            porter_has_active_assignment = Booking.query.filter(
                Booking.porter_id == current_user.id,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            ).first() is not None
            if current_user.porter_available and not porter_has_active_assignment:
                porter_pending_request_count += Booking.query.filter(
                    Booking.station_id == current_user.preferred_station_id,
                    Booking.status == "requested",
                    Booking.porter_id.is_(None),
                ).count()
            porter_on_active_job = any(
                booking.status in {"accepted", "en_route", "arrived", "in_progress"}
                for booking in bookings
            )
        else:
            bookings = []
    else:
        bookings = booking_query.filter_by(passenger_id=current_user.id).order_by(Booking.created_at.desc()).all()
        active_booking_count = sum(booking.status in ACTIVE_BOOKING_STATUSES for booking in bookings)
        passenger_open_bookings = sorted(
            (booking for booking in bookings if booking.status not in {"completed", "cancelled"}),
            key=lambda booking: booking.service_at,
        )
        passenger_completed_count = sum(booking.status == "completed" for booking in bookings)
    if current_user.role == "porter" and current_user.porter_status == "verified":
        porter_available = bool(current_user.porter_available)
    return render_template(
        "porter/dashboard.html" if current_user.role == "porter" else "dashboard.html",
        bookings=bookings,
        pending_porters=pending_porters,
        verified_porters=verified_porters,
        busy_porter_ids=busy_porter_ids,
        porter_available=porter_available,
        porter_active_bookings=porter_active_bookings,
        porter_completed_count=porter_completed_count,
        porter_pending_request_count=porter_pending_request_count,
        porter_today_earnings=porter_today_earnings,
        porter_today_job_count=porter_today_job_count,
        porter_average_rating=porter_average_rating,
        porter_rating_count=porter_rating_count,
        porter_on_active_job=porter_on_active_job,
        active_booking_count=active_booking_count,
        passenger_open_bookings=passenger_open_bookings,
        passenger_completed_count=passenger_completed_count,
        porter_stations=porter_stations,
        catalog_stations=catalog_stations,
        support_requests=support_requests,
        open_support_count=open_support_count,
        admin_accounts=admin_accounts,
        payments_enabled=bool(
            current_app.config.get("RAZORPAY_KEY_ID")
            and current_app.config.get("RAZORPAY_KEY_SECRET")
            and current_app.config.get("RAZORPAY_WEBHOOK_SECRET")
        ),
    )


@bp.get("/admin/passengers")
@login_required
def admin_passengers():
    _require_admin()
    query = request.args.get("q", "").strip()[:100]
    passengers = User.query.filter_by(role="passenger").order_by(User.created_at.desc()).limit(300).all()
    if query:
        needle = query.casefold()
        passengers = [u for u in passengers if needle in u.name.casefold() or needle in u.email.casefold() or needle in (u.phone or "").casefold()]
    return render_template("admin/passengers.html", passengers=passengers, query=query, total_passengers=User.query.filter_by(role="passenger").count())


@bp.get("/admin/porters")
@login_required
def admin_porters():
    _require_admin()
    query = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", "all")
    if status_filter not in {"all", "pending", "verified", "rejected"}:
        status_filter = "all"
    porters = User.query.options(joinedload(User.preferred_station)).filter_by(role="porter").order_by(User.created_at.desc()).limit(400).all()
    if status_filter != "all":
        porters = [u for u in porters if u.porter_status == status_filter]
    if query:
        needle = query.casefold()
        porters = [u for u in porters if needle in u.name.casefold() or needle in u.email.casefold() or needle in (u.phone or "").casefold() or needle in (u.preferred_station.code if u.preferred_station else "").casefold()]
    return render_template("admin/porters.html", porters=porters, query=query, status_filter=status_filter)


@bp.get("/admin/bookings")
@login_required
def admin_bookings():
    _require_admin()
    query = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", "all")
    allowed = {"all", "requested", "assigned", "accepted", "en_route", "arrived", "in_progress", "completed", "declined", "cancelled"}
    if status_filter not in allowed:
        status_filter = "all"
    bookings = _admin_bookings(400)
    if status_filter != "all":
        bookings = [b for b in bookings if b.status == status_filter]
    if query:
        needle = query.casefold()
        bookings = [b for b in bookings if any(needle in value.casefold() for value in (b.public_id, b.passenger.name, b.station.name, b.station.code, b.service.name, b.train_number or ""))]
    available_porters = User.query.options(joinedload(User.preferred_station)).filter_by(role="porter", porter_status="verified", active=True, porter_available=True).order_by(User.name.asc()).all()
    busy_ids = set(db.session.scalars(db.select(Booking.porter_id).where(Booking.porter_id.isnot(None), Booking.status.in_(ACTIVE_BOOKING_STATUSES))).all())
    return render_template("admin/bookings.html", bookings=bookings, query=query, status_filter=status_filter, available_porters=available_porters, busy_ids=busy_ids)


@bp.get("/admin/stations")
@login_required
def admin_stations():
    _require_admin()
    stations = Station.query.options(selectinload(Station.services)).order_by(Station.name).all()
    online_counts = dict(db.session.query(User.preferred_station_id, db.func.count(User.id)).filter_by(role="porter", porter_status="verified", active=True, porter_available=True).group_by(User.preferred_station_id).all())
    return render_template("admin/stations.html", stations=stations, online_counts=online_counts)


@bp.get("/admin/pricing")
@login_required
def admin_pricing():
    _require_admin()
    services = ServiceType.query.options(joinedload(ServiceType.station)).order_by(ServiceType.name, ServiceType.station_id).all()
    services_by_name = {}
    for service in services:
        services_by_name.setdefault(service.name, []).append(service)
    service_groups = [
        {
            "name": name,
            "services": station_services,
            "station_count": len({service.station_id for service in station_services}),
            "active_station_count": len({service.station_id for service in station_services if service.active}),
        }
        for name, station_services in services_by_name.items()
    ]
    return render_template("admin/pricing.html", service_groups=service_groups, service_count=len(service_groups))


@bp.get("/admin/payments")
@login_required
def admin_payments():
    _require_admin()
    attempts = PaymentAttempt.query.options(joinedload(PaymentAttempt.booking).joinedload(Booking.passenger), joinedload(PaymentAttempt.booking).joinedload(Booking.station)).order_by(PaymentAttempt.created_at.desc()).limit(300).all()
    paid_total = sum((Decimal(attempt.amount_paise) / Decimal(100) for attempt in attempts if attempt.status == "paid"), Decimal("0.00"))
    return render_template("admin/payments.html", attempts=attempts, paid_total=paid_total, payments_enabled=bool(current_app.config.get("RAZORPAY_KEY_ID") and current_app.config.get("RAZORPAY_KEY_SECRET") and current_app.config.get("RAZORPAY_WEBHOOK_SECRET")))


@bp.get("/admin/support")
@login_required
def admin_support():
    _require_admin()
    query = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", "all")
    if status_filter not in {"all", "open", "closed"}:
        status_filter = "all"
    tickets = SupportRequest.query.order_by(SupportRequest.created_at.desc()).limit(300).all()
    if status_filter != "all":
        tickets = [ticket for ticket in tickets if ticket.status == status_filter]
    if query:
        needle = query.casefold()
        tickets = [ticket for ticket in tickets if needle in ticket.name.casefold() or needle in ticket.email.casefold() or needle in (ticket.booking_reference or "").casefold() or needle in ticket.message.casefold()]
    return render_template("admin/support.html", tickets=tickets, query=query, status_filter=status_filter, open_count=SupportRequest.query.filter_by(status="open").count())


@bp.get("/admin/reports")
@login_required
def admin_reports():
    _require_admin()
    bookings = _admin_bookings()
    station_rows = []
    stations = Station.query.order_by(Station.name).all()
    for station in stations:
        station_bookings = [b for b in bookings if b.station_id == station.id]
        station_rows.append({"station": station, "count": len(station_bookings), "fare": sum((Decimal(b.estimated_fare or 0) for b in station_bookings), Decimal("0.00"))})
    total = len(bookings)
    completed = sum(1 for b in bookings if b.status == "completed")
    average_fare = sum((Decimal(b.estimated_fare or 0) for b in bookings), Decimal("0.00")) / total if total else Decimal("0.00")
    return render_template("admin/reports.html", station_rows=station_rows, total=total, completed=completed, completion_rate=(completed / total * 100 if total else 0), average_fare=average_fare)


@bp.get("/admin/reports/export")
@login_required
def admin_export_report():
    _require_admin()
    bookings = _admin_bookings()
    stations = Station.query.order_by(Station.name).all()
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Station code", "Station name", "Bookings", "Fare estimates (INR)"])
    for station in stations:
        station_bookings = [booking for booking in bookings if booking.station_id == station.id]
        amount = sum((Decimal(booking.estimated_fare or 0) for booking in station_bookings), Decimal("0.00"))
        writer.writerow([station.code, station.name, len(station_bookings), f"{amount:.2f}"])
    writer.writerow([])
    writer.writerow(["Note", "Booking fare estimates are not captured revenue"])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=rail-sathi-admin-report.csv"})


@bp.get("/admin/notifications")
@login_required
def admin_notifications():
    _require_admin()
    support_requests = SupportRequest.query.filter_by(status="open").order_by(SupportRequest.created_at.desc()).limit(100).all()
    pending_porters = User.query.filter_by(role="porter", porter_status="pending").order_by(User.created_at.desc()).limit(100).all()
    current_user.last_notification_read_at = now_utc()
    db.session.commit()
    return render_template(
        "admin/notifications.html",
        support_requests=support_requests,
        pending_porters=pending_porters,
        pending_count=len(pending_porters),
        open_tickets=len(support_requests),
    )


@bp.get("/admin/settings")
@login_required
def admin_settings():
    _require_admin()
    admin_accounts = User.query.filter_by(role="admin", is_main_admin=False).order_by(User.name.asc()).all() if current_user.is_main_admin else []
    return render_template("admin/settings.html", admin_accounts=admin_accounts)

@bp.post("/porter/presence")
@login_required
def update_porter_presence():
    if current_user.role != "porter":
        abort(403)
    if current_user.porter_status != "verified":
        flash("Complete porter verification before going online.", "error")
        return redirect(url_for("dashboards.porter_verification"))

    available = request.form.get("available")
    if available not in {"0", "1"}:
        abort(400)
    if available == "1" and (
        not current_user.preferred_station
        or not current_user.preferred_station.supported
    ):
        flash("Your station is not currently supported, so you cannot go online.", "error")
        return redirect(url_for("dashboards.index"))

    current_user.porter_available = available == "1"
    db.session.commit()
    flash(
        "You are online and can receive booking requests." if current_user.porter_available
        else "You are offline and will not receive new booking requests.",
        "success",
    )
    return redirect(url_for("dashboards.index"))


@bp.post("/porter-application")
@login_required
def update_porter_application():
    if current_user.role != "porter" or current_user.porter_status == "verified":
        abort(403)

    phone = request.form.get("phone", "").strip()
    station = db.session.get(Station, request.form.get("preferred_station", type=int))
    phone_digits = "".join(character for character in phone if character.isdigit())
    if (
        len(phone) > 30
        or not all(character.isdigit() or character in "+().- " for character in phone)
        or len(phone_digits) < 8
        or len(phone_digits) > 15
        or not station
        or not station.supported
    ):
        flash("Enter a valid phone number and choose a supported station.", "error")
        return redirect(url_for("dashboards.index"))

    current_user.phone = phone[:30]
    current_user.preferred_station_id = station.id
    current_user.porter_status = "pending"
    current_user.porter_available = False
    current_user.porter_review_note = None
    db.session.commit()
    flash("Your porter application details were saved for review.", "success")
    return redirect(url_for("dashboards.index"))


@bp.get("/porter/jobs")
@login_required
def porter_jobs():
    if current_user.role != "porter":
        abort(403)

    status_filter = request.args.get("status", "all").lower()
    if status_filter not in {"all", "active", "completed"}:
        status_filter = "all"
    query = request.args.get("q", "").strip()[:100]
    all_bookings = _porter_bookings(current_user.id) if current_user.porter_status == "verified" else []
    bookings = all_bookings
    if status_filter == "active":
        bookings = [booking for booking in bookings if booking.status in ACTIVE_BOOKING_STATUSES]
    elif status_filter == "completed":
        bookings = [booking for booking in bookings if booking.status == "completed"]
    if query:
        needle = query.casefold()
        bookings = [
            booking for booking in bookings
            if needle in booking.public_id.casefold()
            or needle in booking.station.name.casefold()
            or needle in booking.station.code.casefold()
            or needle in booking.service.name.casefold()
            or needle in (booking.train_number or "").casefold()
            or needle in booking.passenger.name.casefold()
        ]
    return render_template(
        "porter/jobs.html",
        bookings=bookings,
        query=query,
        status_filter=status_filter,
    )


@bp.get("/porter/verification")
@login_required
def porter_verification():
    if current_user.role != "porter":
        abort(403)
    document_status = {
        "verified": "Approved",
        "pending": "In review",
        "rejected": "Update required",
    }.get(current_user.porter_status, "Not submitted")
    documents = [
        {"title": "Profile photograph", "filename": "profile-photo-demo.jpg"},
        {"title": "Identity document", "filename": "demo-id-redacted.pdf"},
        {"title": "Station authorization", "filename": "station-letter-demo.pdf"},
    ]
    return render_template(
        "porter/verification.html",
        document_status=document_status,
        documents=documents,
    )


@bp.get("/porter/requests")
@login_required
def porter_requests():
    if current_user.role != "porter":
        abort(403)
    query = request.args.get("q", "").strip()[:100]
    if current_user.porter_status == "verified":
        assigned_bookings = [
            booking for booking in _porter_bookings(current_user.id)
            if booking.status == "assigned"
        ]
        has_active_assignment = Booking.query.filter(
            Booking.porter_id == current_user.id,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        ).first() is not None
        open_bookings = (
            _open_station_bookings(current_user.preferred_station_id)
            if current_user.porter_available and not has_active_assignment
            else []
        )
        bookings = sorted(assigned_bookings + open_bookings, key=lambda booking: booking.service_at)
    else:
        bookings = []
    if query:
        needle = query.casefold()
        bookings = [booking for booking in bookings if (
            needle in booking.public_id.casefold()
            or needle in booking.station.name.casefold()
            or needle in booking.station.code.casefold()
            or needle in (booking.train_number or "").casefold()
            or needle in booking.passenger.name.casefold()
        )]
    return render_template(
        "porter/worklist.html",
        page_title="Booking requests",
        page_intro="Review new requests and respond before the passenger’s journey begins.",
        eyebrow="RESPOND TO NEW ASSIGNMENTS",
        bookings=bookings,
        query=query,
        list_endpoint="dashboards.porter_requests",
        empty_title="No pending requests",
        empty_copy=(
            "Go online from your dashboard to receive new requests for your station."
            if current_user.porter_status == "verified" and not current_user.porter_available
            else "Finish your current job before accepting another request."
            if current_user.porter_status == "verified" and has_active_assignment
            else "New requests for your station will appear here."
        ),
        show_verification_gate=True,
    )


@bp.get("/porter/active-job")
@login_required
def porter_active_job():
    if current_user.role != "porter":
        abort(403)
    query = request.args.get("q", "").strip()[:100]
    active_statuses = {"accepted", "en_route", "arrived", "in_progress"}
    bookings = _porter_bookings(current_user.id) if current_user.porter_status == "verified" else []
    bookings = [booking for booking in bookings if booking.status in active_statuses]
    if query:
        needle = query.casefold()
        bookings = [booking for booking in bookings if (
            needle in booking.public_id.casefold()
            or needle in booking.station.name.casefold()
            or needle in booking.station.code.casefold()
            or needle in (booking.train_number or "").casefold()
            or needle in booking.passenger.name.casefold()
        )]
    return render_template(
        "porter/worklist.html",
        page_title="Active job",
        page_intro="Follow the handoff from en route to completed.",
        eyebrow="WORK IN PROGRESS",
        bookings=bookings,
        query=query,
        list_endpoint="dashboards.porter_active_job",
        empty_title="No active job right now",
        empty_copy="When you accept a request, the passenger and meeting details will appear here.",
        show_verification_gate=True,
    )


@bp.get("/porter/earnings")
@login_required
def porter_earnings():
    if current_user.role != "porter":
        abort(403)
    bookings = _porter_bookings(current_user.id) if current_user.porter_status == "verified" else []
    completed = [booking for booking in bookings if booking.status == "completed"]
    today = datetime.now(INDIA_TIME).date()
    today_bookings = [booking for booking in completed if _booking_service_date(booking) == today]
    today_total = sum((booking.estimated_fare or Decimal("0.00") for booking in today_bookings), Decimal("0.00"))
    total_value = sum((booking.estimated_fare or Decimal("0.00") for booking in completed), Decimal("0.00"))
    return render_template(
        "porter/earnings.html",
        completed=completed,
        today_total=today_total,
        today_job_count=len(today_bookings),
        completed_value=total_value,
    )


@bp.get("/porter/history")
@login_required
def porter_history():
    if current_user.role != "porter":
        abort(403)
    query = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", "all").lower()
    if status_filter not in {"all", "completed", "declined", "cancelled"}:
        status_filter = "all"
    bookings = _porter_bookings(current_user.id) if current_user.porter_status == "verified" else []
    bookings = [booking for booking in bookings if booking.status in {"completed", "declined", "cancelled"}]
    if status_filter != "all":
        bookings = [booking for booking in bookings if booking.status == status_filter]
    if query:
        needle = query.casefold()
        bookings = [booking for booking in bookings if (
            needle in booking.public_id.casefold()
            or needle in booking.station.name.casefold()
            or needle in booking.station.code.casefold()
            or needle in (booking.train_number or "").casefold()
            or needle in booking.passenger.name.casefold()
        )]
    return render_template(
        "porter/history.html",
        bookings=bookings,
        query=query,
        status_filter=status_filter,
    )


@bp.get("/porter/reviews")
@login_required
def porter_reviews():
    if current_user.role != "porter":
        abort(403)
    reviews = PorterReview.query.filter_by(porter_id=current_user.id).options(
        joinedload(PorterReview.passenger),
        joinedload(PorterReview.booking).joinedload(Booking.station),
    ).order_by(PorterReview.created_at.desc()).all()
    average_rating = sum(review.rating for review in reviews) / len(reviews) if reviews else None
    return render_template("porter/reviews.html", reviews=reviews, average_rating=average_rating)


@bp.get("/porter/notifications")
@login_required
def porter_notifications():
    if current_user.role != "porter":
        abort(403)

    updates = BookingStatusHistory.query.join(
        Booking, BookingStatusHistory.booking_id == Booking.id
    ).filter(
        Booking.porter_id == current_user.id,
        BookingStatusHistory.status.in_(("assigned", "accepted", "declined", "en_route", "arrived", "in_progress", "completed", "cancelled")),
    ).options(
        joinedload(BookingStatusHistory.booking).joinedload(Booking.station),
        joinedload(BookingStatusHistory.booking).joinedload(Booking.service),
    ).order_by(BookingStatusHistory.created_at.desc()).limit(100).all()
    support_updates = SupportRequest.query.filter_by(
        email=current_user.email, status="closed"
    ).filter(SupportRequest.closed_at.is_not(None)).order_by(
        SupportRequest.closed_at.desc()
    ).limit(100).all()
    current_user.last_notification_read_at = now_utc()
    db.session.commit()
    return render_template("porter/notifications.html", updates=updates, support_updates=support_updates)


@bp.route("/porter/profile", methods=["GET", "POST"])
@login_required
def porter_profile():
    if current_user.role != "porter":
        abort(403)

    stations = Station.query.filter_by(supported=True).order_by(Station.name).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        phone_digits = "".join(character for character in phone if character.isdigit())
        station = db.session.get(Station, request.form.get("preferred_station", type=int)) if current_user.porter_status != "verified" else current_user.preferred_station
        if not name or len(name) > 120:
            flash("Enter a name with no more than 120 characters.", "error")
        elif (
            len(phone) > 30
            or not all(character.isdigit() or character in "+().- " for character in phone)
            or not 8 <= len(phone_digits) <= 15
        ):
            flash("Enter a valid phone number with 8 to 15 digits.", "error")
        elif not station or not station.supported:
            flash("Choose a supported station for your porter application.", "error")
        else:
            current_user.name = name
            current_user.phone = phone
            if current_user.porter_status != "verified":
                current_user.preferred_station_id = station.id
                current_user.porter_status = "pending"
                current_user.porter_available = False
                current_user.porter_review_note = None
            db.session.commit()
            flash("Your porter profile has been saved.", "success")
            return redirect(url_for("dashboards.porter_profile"))

    return render_template("porter/profile.html", stations=stations)


@bp.get("/bookings")
@login_required
def passenger_bookings():
    if current_user.role != "passenger":
        abort(403)

    status_filter = request.args.get("status", "all").lower()
    if status_filter not in {"all", "active", "completed", "cancelled"}:
        status_filter = "all"
    query = request.args.get("q", "").strip()[:100]
    bookings = _passenger_bookings(current_user.id)
    if status_filter == "active":
        bookings = [booking for booking in bookings if booking.status not in {"completed", "cancelled"}]
    elif status_filter in {"completed", "cancelled"}:
        bookings = [booking for booking in bookings if booking.status == status_filter]
    if query:
        needle = query.casefold()
        bookings = [
            booking for booking in bookings
            if needle in booking.public_id.casefold()
            or needle in booking.station.name.casefold()
            or needle in booking.station.code.casefold()
            or needle in booking.service.name.casefold()
            or needle in (booking.train_number or "").casefold()
        ]
    return render_template(
        "passenger/bookings.html",
        bookings=bookings,
        query=query,
        status_filter=status_filter,
        payments_enabled=bool(
            current_app.config.get("RAZORPAY_KEY_ID")
            and current_app.config.get("RAZORPAY_KEY_SECRET")
            and current_app.config.get("RAZORPAY_WEBHOOK_SECRET")
        ),
    )


@bp.get("/payments")
@login_required
def passenger_payments():
    if current_user.role != "passenger":
        abort(403)

    bookings = _passenger_bookings(current_user.id)
    payment_rows = [
        {"booking": booking, "attempt": attempt, "amount": Decimal(attempt.amount_paise) / Decimal(100)}
        for booking in bookings
        for attempt in booking.payments
    ]
    payment_rows.sort(key=lambda row: row["attempt"].created_at, reverse=True)
    paid_total = sum(
        (row["amount"] for row in payment_rows if row["attempt"].status == "paid"),
        start=Decimal("0.00"),
    )
    return render_template(
        "passenger/payments.html",
        payment_rows=payment_rows,
        paid_total=paid_total,
        pending_count=sum(row["attempt"].status in {"creating", "created", "authorized", "processing"} for row in payment_rows),
    )


@bp.get("/notifications")
@login_required
def passenger_notifications():
    if current_user.role != "passenger":
        abort(403)

    updates = BookingStatusHistory.query.join(
        Booking, BookingStatusHistory.booking_id == Booking.id
    ).filter(
        Booking.passenger_id == current_user.id
    ).options(
        joinedload(BookingStatusHistory.booking).joinedload(Booking.station),
        joinedload(BookingStatusHistory.booking).joinedload(Booking.service),
    ).order_by(BookingStatusHistory.created_at.desc()).limit(100).all()
    support_updates = SupportRequest.query.filter_by(
        email=current_user.email, status="closed"
    ).filter(SupportRequest.closed_at.is_not(None)).order_by(
        SupportRequest.closed_at.desc()
    ).limit(100).all()
    current_user.last_notification_read_at = now_utc()
    db.session.commit()
    return render_template("passenger/notifications.html", updates=updates, support_updates=support_updates)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def passenger_profile():
    if current_user.role != "passenger":
        abort(403)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        phone_digits = "".join(character for character in phone if character.isdigit())
        if not name or len(name) > 120:
            flash("Enter a name with no more than 120 characters.", "error")
        elif phone and (
            len(phone) > 30
            or not all(character.isdigit() or character in "+().- " for character in phone)
            or not 8 <= len(phone_digits) <= 15
        ):
            flash("Enter a valid phone number, or leave it blank.", "error")
        else:
            current_user.name = name
            current_user.phone = phone or None
            db.session.commit()
            flash("Your profile details have been saved.", "success")
            return redirect(url_for("dashboards.passenger_profile"))

    return render_template("passenger/profile.html")

