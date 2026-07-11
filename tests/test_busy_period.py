import os
import unittest
from unittest.mock import patch

from backend.busy_period import predict_busy_period


class BusyPeriodThresholdTests(unittest.TestCase):
    def test_default_thresholds_keep_existing_behavior(self):
        result = predict_busy_period(2.5, 12, "Friday", {"Friday_12": 1})
        self.assertEqual(result, "very_busy")

    def test_custom_thresholds_can_make_prediction_less_sensitive(self):
        with patch.dict(os.environ, {
            "BUSY_PERIOD_BUSY_RATIO_THRESHOLD": "2.0",
            "BUSY_PERIOD_VERY_BUSY_RATIO_THRESHOLD": "3.0",
        }, clear=False):
            result = predict_busy_period(2.5, 12, "Friday", {"Friday_12": 1})

        self.assertEqual(result, "busy")


if __name__ == "__main__":
    unittest.main()
