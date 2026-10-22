# Rail Sathi project file guide

This guide explains the files that make up the application and which ones are safe to remove. Keep source files and database migrations unless you are intentionally removing the feature they support.

The generated product overview is available at `output/pdf/rail-sathi-features-and-technology.pdf`.

## Project root

| File | Purpose | Guidance |
| --- | --- | --- |
| `.env` | Local secrets and settings such as the Flask secret and optional payment credentials. | Keep private. Never commit or share it. |
| `.env.example` | Safe starter settings for a local setup. | Keep. Copy it to `.env` when setting up a new environment. |
| `.gitignore` | Keeps secrets, local databases, Python caches, and uploads out of version control. | Keep. |
| `README.md` | Setup, workflows, operational notes, and production setup guidance. | Keep. |
| `config.py` | Reads environment settings and defines secure application defaults. | Keep. |
| `requirements.txt` | Python packages needed to run the web application. | Keep. |
| `run.py` | Flask application entry point used for local startup and Flask CLI commands. | Keep. |
| `instance/rail_sathi_dev.db` | Local SQLite database containing development data. | Optional only if you want to reset local data. Back it up first; deleting it removes local accounts and records. |

## Python application files

| File | Purpose | Guidance |
| --- | --- | --- |
| `app/__init__.py` | Builds the Flask app, connects extensions and routes, and registers shared filters and commands. | Keep. |
| `app/admin.py` | Administrator-only actions such as reviewing porters, managing stations, and maintaining services. | Keep. |
| `app/auth.py` | Registration, sign-in, and sign-out. | Keep. |
| `app/bookings.py` | Booking creation and booking status changes. | Keep. |
| `app/dashboards.py` | Passenger, porter, and administrator page data and actions. | Keep. |
| `app/extensions.py` | Shared database, migration, login, CSRF, and Socket.IO extension objects. | Keep. Socket.IO is initialized, but the current app has no event handlers. |
| `app/models.py` | Database tables and relationships for users, stations, services, bookings, history, support, and payments. | Keep. |
| `app/payment_provider.py` | Small server-side client for the Razorpay API. | Keep if online checkout remains part of the app. |
| `app/payments.py` | Checkout, payment signature checks, and Razorpay webhook handling. | Keep if online checkout remains part of the app. |
| `app/public.py` | Public landing, experience, and support pages. | Keep. |
| `app/seed.py` | Adds starter stations and services for local development. | Keep if you use the `flask seed` command. |

`app/__init__.py` is a special Python package filename. Keep it as written; renaming it would break Python imports.

## Page templates

Templates render the pages and forms served by Flask. Files beginning with an underscore are reusable page fragments.

| File | Purpose | Guidance |
| --- | --- | --- |
| `app/templates/base.html` | Shared site shell, navigation, role workspaces, theme controls, and common scripts/styles. | Keep. |
| `app/templates/home.html` | Public landing page. | Keep. |
| `app/templates/journey.html` | Scrolling experience story page. | Keep. |
| `app/templates/auth.html` | Sign-in and registration screens. | Keep. |
| `app/templates/booking_new.html` | Passenger booking form. | Keep. |
| `app/templates/checkout.html` | Razorpay checkout page. | Keep if online checkout remains enabled. |
| `app/templates/dashboard.html` | Shared dashboard entry and staff workspace content. | Keep. |
| `app/templates/support.html` | Public and signed-in support request page. | Keep. |
| `app/templates/errors/error.html` | Shared error page. | Keep. |
| `app/templates/admin/_components.html` | Reusable administrator labels and status components. | Keep. |
| `app/templates/admin/bookings.html` | Administrator booking list and assignment controls. | Keep. |
| `app/templates/admin/dashboard.html` | Administrator operations overview. | Keep. |
| `app/templates/admin/notifications.html` | Administrator activity and notification view. | Keep. |
| `app/templates/admin/passengers.html` | Passenger account list. | Keep. |
| `app/templates/admin/payments.html` | Payment records and payment status view. | Keep. |
| `app/templates/admin/porters.html` | Porter list, availability, and verification review controls. | Keep. |
| `app/templates/admin/pricing.html` | Service fare management. | Keep. |
| `app/templates/admin/reports.html` | Booking and fare estimate reports. | Keep. |
| `app/templates/admin/settings.html` | Organization and administrator account settings. | Keep. |
| `app/templates/admin/stations.html` | Station coverage and service management. | Keep. |
| `app/templates/admin/support.html` | Support ticket inbox. | Keep. |
| `app/templates/passenger/_booking_card.html` | Reusable passenger booking card. | Keep. |
| `app/templates/passenger/bookings.html` | Passenger booking history. | Keep. |
| `app/templates/passenger/notifications.html` | Passenger booking update history. | Keep. |
| `app/templates/passenger/payments.html` | Passenger payment history and receipts. | Keep. |
| `app/templates/passenger/profile.html` | Passenger profile and notification preferences. | Keep. |
| `app/templates/porter/_job_card.html` | Reusable porter job card and status controls. | Keep. |
| `app/templates/porter/dashboard.html` | Porter overview and current job. | Keep. |
| `app/templates/porter/earnings.html` | Porter earnings summary. | Keep. |
| `app/templates/porter/history.html` | Porter completed and past jobs. | Keep. |
| `app/templates/porter/jobs.html` | Porter booking requests and assigned jobs. | Keep. |
| `app/templates/porter/notifications.html` | Porter booking update history. | Keep. |
| `app/templates/porter/profile.html` | Porter contact and profile details. | Keep. |
| `app/templates/porter/reviews.html` | Porter ratings and reviews screen. The current screen is informational/demo content. | Keep if this screen remains in navigation. |
| `app/templates/porter/verification.html` | Porter verification status and submitted document view. | Keep. |
| `app/templates/porter/worklist.html` | Porter work queue. | Keep. |

## Browser styles, scripts, and images

| File | Purpose | Guidance |
| --- | --- | --- |
| `app/static/css/app.css` | Shared application, dashboard, form, and theme styles. | Keep. |
| `app/static/css/landing-page.css` | Public landing page layout and responsive styles. | Keep. Renamed from the temporary `figma-landing.css` name. |
| `app/static/css/landing-page-enhancements.css` | Landing page motion, responsive refinements, and style overrides. | Keep. Renamed from the temporary `figma-home-adapt.css` name. |
| `app/static/css/journey.css` | Experience page layout, image framing, and dark/light themes. | Keep. |
| `app/static/js/app.js` | Landing-page interactions, scroll effects, and shared browser behavior. | Keep. |
| `app/static/js/journey.js` | Experience page scroll progress, chapter state, and porter movement. | Keep. |
| `app/static/icon.svg` | Browser and app icon. | Keep. |
| `app/static/manifest.webmanifest` | Progressive web app name, start page, theme, and icon metadata. | Keep if installable app behavior is desired. |
| `app/static/offline.html` | Fallback shown when a public page cannot be loaded offline. | Keep while the service worker is enabled. |
| `app/static/sw.js` | Service worker that provides the public-page offline fallback. | Keep while offline fallback is enabled. `sw.js` is a standard browser filename. |
| `app/static/images/arrival-reference.png` | Arrival scene image on the experience page. | Keep. |
| `app/static/images/journey-freedom-sunset.jpg` | Third experience scene image. | Keep. |
| `app/static/images/journey-opening-howrah.jpg` | Opening experience scene image. | Keep. |
| `app/static/images/kollam-station.jpg` | Older station image. No current template or script references it. | Safe deletion candidate if you no longer want to keep the original asset. It has not been deleted. |
| `app/static/images/landing-station.png` | Landing page journey section image. | Keep. |
| `app/static/images/porter-trolley.png` | Porter illustration on the landing and experience pages. | Keep. |
| `app/static/images/rail-sathi-logo.png` | Rail Sathi logo used in site navigation and footer. | Keep. |
| `app/static/images/railway-porter-login.png` | Porter photo used on the landing page and account experience. | Keep. |

## Database migration files

Migrations define database changes over time. Alembic connects them by revision IDs, so keep the generated filenames and do not rename or delete individual migrations.

| File | Purpose | Guidance |
| --- | --- | --- |
| `migrations/alembic.ini` | Alembic migration configuration. | Keep. |
| `migrations/env.py` | Connects Alembic to the Flask app and database models. | Keep. |
| `migrations/README` | Generated migration repository note. | Keep. |
| `migrations/script.py.mako` | Template used when new migrations are generated. | Keep. |
| `migrations/versions/2b8eddc6248a_porter_verification_and_admin_operations.py` | Porter verification and administrator operations schema changes. | Keep in the migration chain. |
| `migrations/versions/3a0f81544147_support_inbox.py` | Support inbox schema changes. | Keep in the migration chain. |
| `migrations/versions/92e6b2f3c210_porter_online_status.py` | Porter online availability schema changes. | Keep in the migration chain. |
| `migrations/versions/a71c2e90f436_user_date_of_birth.py` | User date-of-birth field. | Keep in the migration chain. |
| `migrations/versions/b5d4a2c109ef_single_main_admin.py` | Single main administrator constraint. | Keep in the migration chain. |
| `migrations/versions/bf2d90b6a431_post_completion_payments.py` | Payment records and post-completion payment flow. | Keep in the migration chain. |
| `migrations/versions/c41942ab8d11_passenger_notification_read_marker.py` | Notification read marker. | Keep in the migration chain. |
| `migrations/versions/c62ea045cd14_booking_contact_number.py` | Booking contact number. | Keep in the migration chain. |
| `migrations/versions/c91f5a6d902e_submit_legacy_porter_applications.py` | Existing porter application data migration. | Keep in the migration chain. |
| `migrations/versions/d8c9f9ed97ea_active_payment_guard.py` | Prevents conflicting active payment attempts. | Keep in the migration chain. |
| `migrations/versions/e3799c82d589_initial_schema.py` | Initial database schema. | Keep in the migration chain. |
| `migrations/versions/f43f44309c2f_porter_review_feedback.py` | Porter review feedback fields. | Keep in the migration chain. |

## Cleanup guide

### Safe or conditional cleanup

- `app/static/images/kollam-station.jpg` is currently unreferenced by templates and scripts. It can be removed if you do not want to keep the original photo.
- Python `__pycache__` folders and `.pyc` files are generated automatically and can be removed at any time. Python recreates them as needed.
- `.venv` and `.pytest_cache` are ignored local folders. Remove them only when they are not in use; they can be recreated.
- `instance/rail_sathi_dev.db` can be removed only if you accept losing the local development data. Back it up before resetting.
- `.env` can be removed only if you no longer need its local configuration. Keep `.env.example` as the clean setup template.

No files were deleted during this cleanup. The two active landing page stylesheets were given descriptive names, and their template references were updated.
