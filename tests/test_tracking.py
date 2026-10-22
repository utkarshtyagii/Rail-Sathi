import unittest
from datetime import datetime, timedelta, timezone

from app import create_app
from app.extensions import db, socketio
from app.models import Booking, BookingLiveLocation, ServiceType, Station, User
from app.tracking import close_booking_tracking, validate_location_payload


class TrackingTestConfig:
    TESTING = True
    SECRET_KEY = "tracking-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SOCKETIO_MESSAGE_QUEUE = None
    LOCATION_UPDATE_MIN_INTERVAL_SECONDS = 2
    LOCATION_STALE_AFTER_SECONDS = 30
    GOOGLE_MAPS_API_KEY = "test-browser-key"


class LocationValidationTests(unittest.TestCase):
    def test_accepts_valid_coordinate_triplet(self):
        self.assertEqual(validate_location_payload(28.6139, 77.209, 12.5), (28.6139, 77.209, 12.5))

    def test_rejects_invalid_coordinate_triplets(self):
        invalid_values = [
            (91, 0, 1),
            (-91, 0, 1),
            (0, 181, 1),
            (0, -181, 1),
            (0, 0, -1),
            (0, 0, 100_001),
            (float("nan"), 0, 1),
            (0, float("inf"), 1),
            (True, 0, 1),
            ("28.6", 77.2, 1),
            ("north", 0, 1),
            (None, 0, 1),
        ]
        for values in invalid_values:
            with self.subTest(values=values):
                self.assertIsNone(validate_location_payload(*values))


class TrackingSocketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TrackingTestConfig)

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()

            station = Station(name="New Delhi", code="NDLS", region="North")
            db.session.add(station)
            db.session.flush()
            service = ServiceType(station_id=station.id, name="Luggage assistance", base_fare=300)
            passenger = User(name="Passenger", email="passenger@example.test", password_hash="test", role="passenger")
            porter = User(
                name="Assigned porter",
                email="porter@example.test",
                password_hash="test",
                role="porter",
                porter_status="verified",
                preferred_station_id=station.id,
            )
            former_porter = User(
                name="Other porter",
                email="other-porter@example.test",
                password_hash="test",
                role="porter",
                porter_status="verified",
                preferred_station_id=station.id,
            )
            unrelated = User(name="Other passenger", email="other@example.test", password_hash="test", role="passenger")
            db.session.add_all([service, passenger, porter, former_porter, unrelated])
            db.session.flush()
            booking = Booking(
                public_id="TRACKING123",
                passenger_id=passenger.id,
                porter_id=porter.id,
                station_id=station.id,
                service_id=service.id,
                service_at=datetime.now(timezone.utc) + timedelta(days=1),
                pickup="Platform 4",
                pickup_latitude=28.6139,
                pickup_longitude=77.209,
                destination="Main entrance",
                bags=1,
                status="en_route",
                estimated_fare=300,
            )
            db.session.add(booking)
            db.session.commit()

            self.booking_id = booking.id
            self.passenger_id = passenger.id
            self.porter_id = porter.id
            self.former_porter_id = former_porter.id
            self.unrelated_id = unrelated.id
        self.socket_clients = []

    def tearDown(self):
        for client in self.socket_clients:
            if client.is_connected():
                client.disconnect()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _socket_client(self, user_id):
        flask_client = self.app.test_client()
        with flask_client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        client = socketio.test_client(self.app, flask_test_client=flask_client)
        self.socket_clients.append(client)
        return client

    def _http_client(self, user_id):
        flask_client = self.app.test_client()
        with flask_client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return flask_client

    def _join(self, client, booking_id=None):
        return client.emit(
            "tracking:join",
            {"bookingId": booking_id or self.booking_id},
            callback=True,
        )

    @staticmethod
    def _events(client, event_name):
        return [packet for packet in client.get_received() if packet["name"] == event_name]

    def test_only_booking_participants_can_join_and_share(self):
        passenger = self._socket_client(self.passenger_id)
        porter = self._socket_client(self.porter_id)
        unrelated = self._socket_client(self.unrelated_id)
        former_porter = self._socket_client(self.former_porter_id)

        self.assertTrue(self._join(passenger)["ok"])
        self.assertTrue(self._join(porter)["ok"])
        unrelated_join = self._join(unrelated)
        self.assertFalse(unrelated_join["ok"])
        self.assertFalse(self._join(former_porter)["ok"])
        unrelated_update = unrelated.emit(
            "tracking:location:update",
            {
                "bookingId": self.booking_id,
                "latitude": 28.614,
                "longitude": 77.21,
                "accuracyM": 8,
            },
            callback=True,
        )
        self.assertEqual(unrelated_update["code"], "booking_unavailable")

        for client in (passenger, porter, unrelated, former_porter):
            client.get_received()

        update_ack = passenger.emit(
            "tracking:location:update",
            {
                "bookingId": self.booking_id,
                "latitude": 28.614,
                "longitude": 77.21,
                "accuracyM": 8.0,
            },
            callback=True,
        )
        self.assertTrue(update_ack["ok"])
        self.assertEqual(len(self._events(passenger, "tracking:location")), 1)
        porter_updates = self._events(porter, "tracking:location")
        self.assertEqual(len(porter_updates), 1)
        self.assertEqual(porter_updates[0]["args"][0]["role"], "passenger")
        self.assertEqual(self._events(unrelated, "tracking:location"), [])
        self.assertEqual(self._events(former_porter, "tracking:location"), [])

    def test_passenger_and_porter_booking_pages_render_map_and_controls(self):
        passenger_dashboard = self._http_client(self.passenger_id).get("/dashboard/")
        self.assertEqual(passenger_dashboard.status_code, 200)
        self.assertIn(b'data-booking-tracking', passenger_dashboard.data)

        passenger_response = self._http_client(self.passenger_id).get("/dashboard/bookings?status=active")
        self.assertEqual(passenger_response.status_code, 200)
        self.assertIn(b'data-booking-tracking', passenger_response.data)
        self.assertIn(b'data-start-sharing', passenger_response.data)
        self.assertIn(b'js/tracking.js', passenger_response.data)

        porter_response = self._http_client(self.porter_id).get("/dashboard/porter/active-job")
        self.assertEqual(porter_response.status_code, 200)
        self.assertIn(b'data-booking-tracking', porter_response.data)
        self.assertIn(b'Start sharing location', porter_response.data)
        self.assertIn(b'js/tracking.js', porter_response.data)

        porter_dashboard = self._http_client(self.porter_id).get("/dashboard/")
        self.assertEqual(porter_dashboard.status_code, 200)
        self.assertIn(b'data-booking-tracking', porter_dashboard.data)

    def test_maps_config_only_returns_browser_key_without_caching(self):
        response = self.app.test_client().get("/maps/config")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"apiKey": "test-browser-key"})
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_update_requires_join_and_rejects_bad_coordinates(self):
        passenger = self._socket_client(self.passenger_id)
        missing_join = passenger.emit(
            "tracking:location:update",
            {"bookingId": self.booking_id, "latitude": 28, "longitude": 77, "accuracyM": 3},
            callback=True,
        )
        self.assertEqual(missing_join["code"], "join_required")

        self.assertTrue(self._join(passenger)["ok"])
        invalid = passenger.emit(
            "tracking:location:update",
            {"bookingId": self.booking_id, "latitude": 999, "longitude": 77, "accuracyM": 3},
            callback=True,
        )
        self.assertEqual(invalid["code"], "invalid_coordinates")
        with self.app.app_context():
            self.assertEqual(BookingLiveLocation.query.filter_by(booking_id=self.booking_id).count(), 1)
            location = BookingLiveLocation.query.filter_by(booking_id=self.booking_id).one()
            self.assertFalse(location.is_sharing)
            self.assertIsNone(location.latitude)

    def test_stopping_share_clears_precise_fix_and_broadcasts(self):
        passenger = self._socket_client(self.passenger_id)
        porter = self._socket_client(self.porter_id)
        self.assertTrue(self._join(passenger)["ok"])
        self.assertTrue(self._join(porter)["ok"])
        passenger.get_received()
        porter.get_received()
        self.assertTrue(passenger.emit(
            "tracking:location:update",
            {"bookingId": self.booking_id, "latitude": 28.614, "longitude": 77.21, "accuracyM": 8},
            callback=True,
        )["ok"])
        passenger.get_received()
        porter.get_received()

        self.assertTrue(passenger.emit("tracking:stop", {"bookingId": self.booking_id}, callback=True)["ok"])
        with self.app.app_context():
            location = BookingLiveLocation.query.filter_by(booking_id=self.booking_id, user_id=self.passenger_id).one()
            self.assertFalse(location.is_sharing)
            self.assertIsNone(location.latitude)
        self.assertEqual(len(self._events(porter, "tracking:participant_stopped")), 1)
        with self.app.app_context():
            location = BookingLiveLocation.query.filter_by(booking_id=self.booking_id, user_id=self.passenger_id).one()
            self.assertTrue(location.sharing_opted_out)

    def test_server_rate_limits_updates_per_participant(self):
        passenger = self._socket_client(self.passenger_id)
        self.assertTrue(self._join(passenger)["ok"])
        payload = {
            "bookingId": self.booking_id,
            "latitude": 28.614,
            "longitude": 77.21,
            "accuracyM": 8,
        }
        self.assertTrue(passenger.emit("tracking:location:update", payload, callback=True)["ok"])
        passenger.get_received()
        rate_limited = passenger.emit(
            "tracking:location:update",
            {**payload, "latitude": 28.615},
            callback=True,
        )
        self.assertEqual(rate_limited["code"], "rate_limited")
        with self.app.app_context():
            location = BookingLiveLocation.query.filter_by(
                booking_id=self.booking_id,
                user_id=self.passenger_id,
            ).one()
            self.assertEqual(location.latitude, payload["latitude"])
        self.assertEqual(self._events(passenger, "tracking:location"), [])

    def test_location_updates_are_rejected_until_porter_accepts(self):
        with self.app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            booking.status = "assigned"
            db.session.commit()
        passenger = self._socket_client(self.passenger_id)
        self.assertTrue(self._join(passenger)["ok"])
        result = passenger.emit(
            "tracking:location:update",
            {"bookingId": self.booking_id, "latitude": 28.614, "longitude": 77.21, "accuracyM": 8},
            callback=True,
        )
        self.assertEqual(result["code"], "booking_not_accepted")

    def test_explicit_opt_out_can_be_resumed_only_by_booking_participant(self):
        passenger = self._socket_client(self.passenger_id)
        unrelated = self._socket_client(self.unrelated_id)
        self.assertTrue(self._join(passenger)["ok"])
        self.assertEqual(passenger.emit("tracking:stop", {"bookingId": self.booking_id}, callback=True), {"ok": True})
        denied = unrelated.emit("tracking:resume", {"bookingId": self.booking_id}, callback=True)
        self.assertEqual(denied["code"], "booking_unavailable")
        resumed = passenger.emit("tracking:resume", {"bookingId": self.booking_id}, callback=True)
        self.assertTrue(resumed["ok"])
        with self.app.app_context():
            location = BookingLiveLocation.query.filter_by(booking_id=self.booking_id, user_id=self.passenger_id).one()
            self.assertFalse(location.sharing_opted_out)

    def test_participants_can_update_independently(self):
        passenger = self._socket_client(self.passenger_id)
        porter = self._socket_client(self.porter_id)
        self.assertTrue(self._join(passenger)["ok"])
        self.assertTrue(self._join(porter)["ok"])
        passenger.get_received()
        porter.get_received()
        self.assertTrue(passenger.emit("tracking:location:update", {
            "bookingId": self.booking_id, "latitude": 28.6, "longitude": 77.2, "accuracyM": 8,
        }, callback=True)["ok"])
        self.assertTrue(porter.emit("tracking:location:update", {
            "bookingId": self.booking_id, "latitude": 28.61, "longitude": 77.21, "accuracyM": 6,
        }, callback=True)["ok"])
        passenger_updates = self._events(passenger, "tracking:location")
        self.assertEqual([event["args"][0]["role"] for event in passenger_updates], ["passenger", "porter"])
        self.assertEqual([event["args"][0]["role"] for event in self._events(porter, "tracking:location")], ["passenger", "porter"])

    def test_terminal_booking_close_deletes_locations_and_closes_participants(self):
        passenger = self._socket_client(self.passenger_id)
        porter = self._socket_client(self.porter_id)
        self.assertTrue(self._join(passenger)["ok"])
        self.assertTrue(self._join(porter)["ok"])
        passenger.get_received()
        porter.get_received()
        passenger.emit(
            "tracking:location:update",
            {"bookingId": self.booking_id, "latitude": 28.614, "longitude": 77.21, "accuracyM": 8},
            callback=True,
        )
        passenger.get_received()
        porter.get_received()

        with self.app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            booking.status = "completed"
            db.session.commit()
            close_booking_tracking(self.booking_id)
            self.assertEqual(BookingLiveLocation.query.filter_by(booking_id=self.booking_id).count(), 0)

        self.assertEqual(len(self._events(passenger, "tracking:closed")), 1)
        self.assertEqual(len(self._events(porter, "tracking:closed")), 1)


if __name__ == "__main__":
    unittest.main()
