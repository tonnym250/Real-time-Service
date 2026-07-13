import datetime
import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


class TelegramConfigTests(unittest.TestCase):
    def test_send_telegram_message_uses_environment_config(self):
        sys.modules.pop("backend.api_server", None)

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "test-chat-id"},
            clear=False,
        ):
            backend_api_server = importlib.import_module("backend.api_server")

            with patch("backend.api_server.requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                result = backend_api_server.send_telegram_message("hello")

            self.assertTrue(result)
            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(payload["chat_id"], "test-chat-id")
            self.assertEqual(payload["text"], "hello")


class CleanupTests(unittest.TestCase):
    def test_cleanup_old_requests_is_disabled_by_default(self):
        import backend.api_server as backend_api_server

        old_timestamp = (datetime.datetime.now() - datetime.timedelta(minutes=20)).isoformat()
        ref = MagicMock()
        ref.get.return_value = {
            "req-1": {
                "event_type": "requested",
                "timestamp": old_timestamp,
            }
        }

        with patch.dict(os.environ, {}, clear=False):
            with patch.object(backend_api_server.db, "reference", return_value=ref):
                result = backend_api_server.cleanup_old_requests(max_age_minutes=10)

        self.assertEqual(result["cleaned"], 0)
        ref.child.assert_not_called()


class PredictDemandTests(unittest.TestCase):
    def test_predict_demand_uses_table_registry_when_stats_missing(self):
        import backend.api_server as backend_api_server

        tables_ref = MagicMock()
        tables_ref.get.return_value = {"table_1": {}, "table_2": {}, "table_3": {}}

        with patch.object(backend_api_server.db, "reference", side_effect=[tables_ref]):
            with patch.object(backend_api_server, "predict", return_value=["low", "occasional", "recurring"]) as mock_predict:
                with patch.object(backend_api_server, "make_record", side_effect=lambda table_id, stats: {"table_id": table_id}) as mock_make_record:
                    with backend_api_server.app.test_request_context('/predict_demand', method='POST', json={}):
                        response = backend_api_server.predict_demand()

        payload = response[0].get_json()
        self.assertEqual(payload["predictions"], {"table_1": "low", "table_2": "occasional", "table_3": "recurring"})
        self.assertEqual(mock_make_record.call_count, 3)
        mock_predict.assert_called_once()


class AutoRetrainTests(unittest.TestCase):
    def test_should_auto_retrain_when_threshold_is_reached(self):
        import backend.api_server as backend_api_server

        self.assertTrue(backend_api_server.should_auto_retrain(100, 0, 100))
        self.assertTrue(backend_api_server.should_auto_retrain(150, 50, 100))
        self.assertFalse(backend_api_server.should_auto_retrain(90, 0, 100))
        self.assertFalse(backend_api_server.should_auto_retrain(105, 100, 100))


class DemandModelTrainingTests(unittest.TestCase):
    def test_train_model_handles_tiny_imbalanced_dataset(self):
        import backend.demand_model as demand_model

        records = [
            {
                "hour": 12,
                "weekday": "Monday",
                "total_requests": 5,
                "recent_24h": 2,
                "unique_days": 1,
                "peak_hour_count": 2,
                "label": "low",
            },
            {
                "hour": 18,
                "weekday": "Monday",
                "total_requests": 10,
                "recent_24h": 4,
                "unique_days": 2,
                "peak_hour_count": 3,
                "label": "occasional",
            },
            {
                "hour": 20,
                "weekday": "Friday",
                "total_requests": 20,
                "recent_24h": 6,
                "unique_days": 3,
                "peak_hour_count": 4,
                "label": "recurring",
            },
        ]

        result = demand_model.train_model(records, save=False)

        self.assertIn("accuracy", result)
        self.assertIn("model_path", result)
        self.assertGreaterEqual(result["accuracy"], 0.0)


if __name__ == "__main__":
    unittest.main()
