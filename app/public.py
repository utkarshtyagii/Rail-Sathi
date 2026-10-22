from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, current_app, flash, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from .extensions import db
from .models import Station, SupportRequest

bp = Blueprint("public", __name__)


@bp.get("/maps/config")
def maps_config():
    """Return only the browser-restricted Google Maps key used by tracking pages."""
    response = make_response(jsonify(apiKey=current_app.config.get("GOOGLE_MAPS_API_KEY", "")))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboards.index"))

    query = request.args.get("q", "").strip()
    stations = Station.query.filter(Station.supported.is_(True))
    if query:
        stations = stations.filter((Station.name.ilike(f"%{query}%")) | (Station.code.ilike(f"%{query}%")))
    return render_template("home.html", stations=stations.order_by(Station.name).all(), query=query)


@bp.get("/journey")
def journey():
    return render_template("journey.html")


@bp.route("/support", methods=["GET", "POST"])
def support():
    support_requests = []
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        submitted_email = request.form.get("email", "").strip()
        booking_reference = request.form.get("booking_reference", "").strip().upper()[:16]
        message = request.form.get("message", "").strip()

        if current_user.is_authenticated:
            name = name or current_user.name
            submitted_email = submitted_email or current_user.email

        try:
            email = validate_email(submitted_email, check_deliverability=False).normalized
        except EmailNotValidError:
            email = ""

        if not name or len(name) > 120 or not email or len(email) > 255 or not 10 <= len(message) <= 1500:
            flash("Enter your name, a valid email address, and a message of at least 10 characters.", "error")
        else:
            support_request = SupportRequest(
                name=name,
                email=email,
                booking_reference=booking_reference or None,
                message=message,
            )
            db.session.add(support_request)
            db.session.commit()
            flash(f"Your support request #{support_request.id} has been sent to the Rail Sathi team.", "success")
            return redirect(url_for("public.support"))

    if current_user.is_authenticated and current_user.role in {"passenger", "porter"}:
        support_requests = SupportRequest.query.filter_by(email=current_user.email).order_by(
            SupportRequest.created_at.desc()
        ).limit(10).all()
    return render_template("support.html", support_requests=support_requests)

