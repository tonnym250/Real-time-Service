import importlib
import os
import sys
import threading
import unittest
from unittest.mock import patch

from backend import busy_period
from backend.demand_model import classify_demand_from_stats, describe_demand_pattern


class BusyPeriodTests(unittest.TestCase):
    def test_single_request_does_not_trigger_overload(self):
        period = busy_period.predict_busy_period(
            current_table_requests=1,
            current_hour=13,
            current_day="Monday",
            baseline={"Monday_13": 3.0}
        )
        self.assertEqual(period, "normal")

    def test_busy_description_uses_recommendation_style_copy(self):
        description = busy_period.describe_busy_period(
            period='busy',
            hour=18,
            day='Thursday',
            current_requests=4,
            baseline_average=2.0,
        )
        self.assertIn('Compared with the usual Thursday 18:00 pattern', description)
        self.assertIn('A little extra support may help', description)

    def test_demand_labels_distinguish_low_and_high_activity_tables(self):
        low_stats = {
            'totalRequests': 5,
            'recent24': 1,
            'days': {'Monday'},
            'recentHoursPeak': 1,
            'topHour': 12,
            'topDay': 'Monday',
        }
        medium_stats = {
            'totalRequests': 10,
            'recent24': 4,
            'days': {'Monday', 'Tuesday'},
            'recentHoursPeak': 3,
            'topHour': 12,
            'topDay': 'Monday',
        }
        high_stats = {
            'totalRequests': 20,
            'recent24': 8,
            'days': {'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'},
            'recentHoursPeak': 5,
            'topHour': 12,
            'topDay': 'Monday',
        }

        self.assertEqual(classify_demand_from_stats(low_stats), 'low')
        self.assertEqual(classify_demand_from_stats(medium_stats), 'occasional')
        self.assertEqual(classify_demand_from_stats(high_stats), 'recurring')

    def test_describe_demand_pattern_returns_user_friendly_ml_message(self):
        message = describe_demand_pattern('recurring', {'topHour': 19, 'topDay': 'Friday'}, 'Table 1')
        self.assertIn('Table 1', message)
        self.assertIn('friday', message.lower())
        self.assertIn('busy', message.lower())
        self.assertNotIn('low demand', message.lower())


class TelegramConfigTests(unittest.TestCase):
    def test_send_telegram_message_uses_environment_config(self):
        sys.modules.pop("backend.api_server", None)

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "test-chat-id"},
            clear=False,
        ):
            backend_api_server = importlib.import_module("backend.api_server")
            backend_api_server = importlib.reload(backend_api_server)

            with patch("backend.api_server.requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                result = backend_api_server.send_telegram_message("hello")

            self.assertTrue(result)
            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(payload["chat_id"], "test-chat-id")
            self.assertEqual(payload["text"], "hello")

    def test_dispatch_background_notification_starts_thread(self):
        sys.modules.pop("backend.api_server", None)
        backend_api_server = importlib.import_module("backend.api_server")
        backend_api_server = importlib.reload(backend_api_server)

        completed = threading.Event()

        def fake_send(message):
            completed.set()
            return True

        with patch("backend.api_server.send_telegram_message", side_effect=fake_send):
            started = backend_api_server.dispatch_background_notification("hello")

        self.assertTrue(started)
        self.assertTrue(completed.wait(timeout=1))

    def test_serving_table_marks_all_pending_requests_as_served(self):
        sys.modules.pop("backend.api_server", None)
        backend_api_server = importlib.import_module("backend.api_server")
        backend_api_server = importlib.reload(backend_api_server)

        class FakePushRef:
            def __init__(self, parent, key):
                self.parent = parent
                self.key = key

            def set(self, payload):
                self.parent._store[self.parent._path][self.key] = payload

        class FakeRef:
            def __init__(self, store, path):
                self._store = store
                self._path = path

            def child(self, key):
                return FakeRef(self._store, f"{self._path}/{key}" if self._path else key)

            def get(self):
                return self._store.get(self._path, {})

            def update(self, payload):
                if self._path.startswith("tables/"):
                    table_id = self._path.split("/", 1)[1]
                    current = self._store.setdefault("tables", {}).setdefault(table_id, {})
                    current.update(payload)
                elif self._path.startswith("requests/"):
                    parent = self._path.split("/", 1)[0]
                    key = self._path.split("/", 1)[1]
                    self._store.setdefault(parent, {})[key] = {
                        **self._store.setdefault(parent, {}).get(key, {}),
                        **payload,
                    }

            def push(self):
                if self._path != "requests":
                    raise AssertionError("push should only be used for requests")
                key = f"auto-{len(self._store.setdefault('requests', {})) + 1}"
                return FakePushRef(self, key)

        class FakeDb:
            def __init__(self):
                self._store = {"requests": {}, "tables": {}}

            def reference(self, path):
                return FakeRef(self._store, path)

        fake_db = FakeDb()
        fake_db._store["requests"]["req-1"] = {
            "table_id": "table_1",
            "event_type": "requested",
            "timestamp": "2026-07-09T10:00:00",
        }
        backend_api_server.db = fake_db

        with patch("backend.api_server.dispatch_background_notification", return_value=True):
            with backend_api_server.app.test_client() as client:
                response = client.post(
                    "/arduino_button",
                    json={"table_id": "table_1", "event_type": "served"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_db._store["requests"]["req-1"]["event_type"], "served")
        self.assertEqual(fake_db._store["tables"]["table_1"]["status"], "served")


if __name__ == "__main__":
    unittest.main()
