# Rail Sathi

For a file-by-file map and cleanup guidance, see [project-file-guide.md](project-file-guide.md).

Rail Sathi is a Flask application for booking railway porter assistance. It includes passenger accounts and bookings, porter applications, staff verification and assignment, porter acceptance or decline, status tracking, support requests, and Razorpay checkout after service completion.

## Run locally on Windows

Open PowerShell in this folder and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and replace `SECRET_KEY` with a long random value. The example uses SQLite, so PostgreSQL is not needed for a local preview. Then initialize the database and starter stations:

```powershell
python -m flask --app run.py db upgrade
python -m flask --app run.py seed
python run.py
```

Open `http://127.0.0.1:5000`. Leave the terminal running while you use the site. If PowerShell shows `>>`, press **Ctrl+C** once to return to the normal prompt before entering a command.

The migration files are included in the project. Use `flask db upgrade` for normal setup and future schema updates; `flask db init` is only for creating a brand-new migration repository.

## Use the booking and operations flow

1. Register a passenger account and submit a booking request. The passenger provides a contact number for that trip; it is shown to the assigned porter and station staff so they can coordinate the meeting. The passenger sees a porter’s phone number after the porter accepts.
2. Register a porter applicant with a phone number and preferred station. The applicant dashboard lets them update those details.
3. Create the account that will be your single main administrator, then promote it from this folder:

   ```powershell
   python -m flask --app run.py create-main-admin admin@example.com
   ```

   Replace the email with the account you registered. The main administrator can create and deactivate other administrators from the dashboard. Only the main administrator can manage staff accounts.

4. Sign in as the administrator. Review porter applications only after completing identity checks through your approved process. Verify or reject applicants, then assign each booking to an online, verified porter for the same station. Porters can switch their availability from the dashboard. The porter must accept before progressing the job; a declined job can be reassigned.
5. Use **Stations and services** on the staff dashboard to hide or reopen a station, update each service's base fare, and make a service available or unavailable.
6. The porter can advance an accepted job from en route to arrived. On arrival, the passenger gets a six-digit handoff code in their booking page; the porter must enter it before starting assistance. A new passenger confirmation code is then issued, and the porter must enter it to complete the job. Each code expires after 15 minutes and locks after five incorrect entries. This prototype displays codes in the passenger account only; it does not send SMS. After completion, the passenger can leave one rating and optional feedback for the porter, then pay through Razorpay when payment credentials are configured.

Passengers and visitors can send a support request from **Support**. Requests are saved in the staff dashboard, where an administrator can mark them handled. Replies are not sent automatically.

## Current service behavior

- The server calculates the booking estimate from the selected service base fare plus ₹35 for each bag after the first. Browser values are never trusted for the saved fare.
- Booking times are entered and displayed in India Standard Time; audit timestamps are stored in UTC and displayed in India Standard Time.
- Booking requests and status changes are recorded in the database with an audit history.
- Starting porter assistance requires the passenger's booking-specific handoff code. The code is derived using the server secret, is never stored as plaintext, expires after 15 minutes, and allows at most five incorrect attempts. Passengers can regenerate it while the porter is marked arrived. The current prototype displays it in the passenger account; no SMS is sent.
- Completing porter assistance requires a second booking-specific passenger confirmation code. Passengers can leave one 1–5 star rating and optional written feedback for a completed booking; porters can view their received ratings and comments.
- Administrator notification counts and queues show open support requests and porter applications awaiting verification. Passenger and porter booking-status changes remain visible in their respective portals and no longer create admin notifications.
- Verified porters explicitly switch online to receive new assignments; offline porters are excluded from assignment choices.
- Porter applicants cannot view passenger booking details until verified and assigned. A porter who declines or loses an assignment no longer sees that booking's passenger contact details.
- Administrator routes are restricted to staff accounts. One main administrator is enforced in the database; only that account can create or deactivate regular administrators. Registration does not offer an administrator role.
- The final fare is the server-calculated estimate saved with the booking. Razorpay orders are created on the server only after completion. A signed checkout response is checked against Razorpay's Payments API, and a signed webhook confirms captured payments; browser redirects alone never mark an attempt paid.
- If Razorpay is not configured, the app clearly displays that online payment is unavailable. It does not create a fake payment or mark a booking paid. Arrange a payment process before accepting real bookings.
- Support messages are stored in the application database and reviewed manually; no email reply or SMS notification is sent.
- Accepted active bookings show a Google Map with saved pickup/destination pins when provided and real participant GPS fixes. Sharing requires browser permission, is scoped to that booking, and is restricted to its passenger and assigned verified porter. No route distance or ETA is simulated.
- A participant's latest consented GPS fix is cleared when they stop sharing, withdraw browser permission, or the booking ends. Old fixes are labeled stale and are not presented as current live positions.

## Live location prototype

Run the existing Flask app with `python run.py` after installing `requirements.txt` and upgrading the database. Add `GOOGLE_MAPS_API_KEY=...` to `.env` using a browser key restricted to your website referrers and to the Maps JavaScript API. Enable the Maps JavaScript API and billing in the Google Cloud project. The key is returned to the tracking page for browser use, so it is visible to visitors and must be protected by those Google Cloud restrictions. Pickup and destination may each have an optional pin saved from the passenger's current device location; typed text is never geocoded or used to invent a pin. When the porter accepts the booking, both participants' active booking pages can request location permission once and automatically share when browser permission is granted. Either participant may stop sharing and later deliberately resume. A fresh browser GPS fix is sent through Flask-SocketIO about every 15 seconds even if the device is stationary, with movement updates between heartbeats; updates stop when the booking ends or browser permission is revoked. Websites cannot guarantee background sharing while a tab is backgrounded, a device sleeps, or the browser closes. Passenger and porter locations are only sent to the participants of that active booking.

Browser geolocation requires HTTPS on a deployed site; `localhost` and `127.0.0.1` are allowed for local development. Add the local development referrers to the Google Cloud key restrictions when testing locally. Set `LOCATION_UPDATE_MIN_INTERVAL_SECONDS` to control the server-side minimum update interval and `LOCATION_STALE_AFTER_SECONDS` for the stale-fix indicator. For multiple application workers or instances, set `SOCKETIO_MESSAGE_QUEUE` to a shared Redis URL so participant-room broadcasts reach the other workers; a single local process does not need Redis.

Run the focused tracking checks with `python -m unittest tests.test_tracking` and check browser JavaScript syntax with `node --check app/static/js/tracking.js` and `node --check app/static/js/pickup-location.js`.

## Before public launch

Connect and configure a real payment provider, transactional email and SMS, request rate limiting and spam protection. Google Maps requires an enabled Maps JavaScript API and billing-enabled Cloud project; restrict the browser key by website referrer and API. Never mark a payment successful based on a browser redirect; verify provider signatures on the server. Review the live-location privacy notice, retention policy, and deployment provider terms before handling real passenger trips.

| Capability | External setup still needed |
|---|---|
| Online payments and refunds | Razorpay account, test/live Key ID and Key Secret, and a webhook signing secret. Configure the deployed `/payments/webhook` URL for `payment.captured` and `payment.failed`. Refunds must currently be handled in the Razorpay dashboard and reconciled manually. |
| Email replies and account recovery | Transactional email or SMTP account, verified sender address/domain, and credentials |
| SMS delivery for passenger confirmation codes | Authorized SMS provider account, API credentials, and approved sender/template configuration; the prototype currently shows both codes only in the passenger's signed-in booking page |
| Routing and live ETA | A routing/ETA provider and service integration; the prototype only displays current GPS positions on a map |
| Push notifications | Firebase project and FCM service credentials |
| Background delivery jobs | Redis service URL and a worker process if email/SMS/push delivery runs asynchronously |

Use Razorpay **test mode** first. Add its Key ID, Key Secret, and a webhook secret to `.env`; keep the webhook secret distinct from the API Key Secret. Set the webhook URL after deployment, since Razorpay must reach the public HTTPS deployment. Use the test credentials and webhook from the same Razorpay account/environment. Then run the migration command above, restart the app, complete a test booking through porter assignment and completion, and use Razorpay's test payment methods. Move to live credentials only after your real service, refund, support, and settlement processes are ready.

These values belong in the local `.env` or deployment secret manager, never in source files or chat. Email, SMS, and push are not connected. Location sharing uses actual device GPS only after explicit participant consent; no location or movement is simulated.

For a shared or production installation, use PostgreSQL, HTTPS, a strong secret, secure cookies, database backups, monitoring, and a production WSGI server. Set `RAILSATHI_ENV=production`, `DATABASE_URL` in `.env` to the PostgreSQL connection string, and `COOKIE_SECURE=true` when HTTPS is enabled. Production startup rejects a missing or weak secret and insecure session cookies. Do not commit `.env` or provider credentials.

The staff verification screen records an operational approval; it does not verify identity documents electronically. Establish a safe identity-review procedure and support contact before accepting real porter applications.
