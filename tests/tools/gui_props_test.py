"""Props failures and older engines must not break launcher status."""

from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gui"))
from engine_props import fetch_props


class PropsTest(unittest.TestCase):
    def test_bounded_json_read_and_missing_fields(self):
        client = MagicMock()
        response = client.open.return_value.__enter__.return_value
        for body, expected in ((b'{"modalities":{"vision":false}}', {"modalities": {"vision": False}}),
                               (b'{}', {}), (b'[]', None), (b'null', None), (b'broken', None)):
            with self.subTest(body=body):
                response.read.return_value = body
                self.assertEqual(fetch_props(client, "http://127.0.0.1:8080/props"), expected)
                response.read.assert_called_with(65536)
        client.open.assert_called_with("http://127.0.0.1:8080/props", timeout=0.5)

    def test_unavailable_props_are_retried_without_errors(self):
        stream = BytesIO()
        for error in (OSError("timeout"), urllib.error.URLError("offline"),
                      urllib.error.HTTPError("http://localhost/props", 404, "old engine", {}, stream)):
            with self.subTest(error=error):
                client = Mock()
                client.open.side_effect = error
                self.assertIsNone(fetch_props(client, "http://localhost/props"))
        self.assertTrue(stream.closed)
