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
bff27a1 (update project)


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
bff27a1 (update project)


if __name__ == "__main__":
    unittest.main()
