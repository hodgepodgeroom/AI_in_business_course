import unittest
from unittest.mock import patch
import model


class ModelTests(unittest.TestCase):
    @patch("model.requests.post")
    def test_chat_completions_contract(self, post):
        response = post.return_value
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": '{"status":"ok"}'}}]
        }
        shape = model.schema_object({"status": model.STRING})
        self.assertEqual(model.chat("qwen3.5", "Проверка", shape), {"status": "ok"})
        req = post.call_args.kwargs["json"]
        self.assertEqual(req["model"], "qwen3.5")
        self.assertEqual(req["response_format"]["json_schema"]["schema"], shape)
        response.json.return_value = {"choices": [{"message": {"content": "ошибка"}}]}
        with self.assertRaises(RuntimeError):
            model.chat("qwen3.5", "Проверка", shape)
