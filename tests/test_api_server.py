import os
import sys
import unittest
from unittest.mock import patch


class TelegramConfigTests(unittest.TestCase):
    def test_send_telegram_message_uses_environment_config(self):
        sys.modules.pop("api_server", None)

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "test-chat-id"},
            clear=False,
        ):
            import api_server

            with patch("api_server.requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                result = api_server.send_telegram_message("hello")

            self.assertTrue(result)
            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(payload["chat_id"], "test-chat-id")
            self.assertEqual(payload["text"], "hello")


if __name__ == "__main__":
    unittest.main()
