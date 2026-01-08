import unittest

from mcp_fetch.server import _merge_query, _only_http_https, _parse_body


class TestServerHelpers(unittest.TestCase):
	def test_only_http_https_rejects_non_http(self) -> None:
		with self.assertRaises(ValueError):
			_only_http_https("file:///etc/passwd")

	def test_only_http_https_requires_host(self) -> None:
		with self.assertRaises(ValueError):
			_only_http_https("https:///path-only")

	def test_merge_query_appends(self) -> None:
		url = _merge_query("https://example.com/path?a=1", {"b": 2, "c": None})
		self.assertEqual(url, "https://example.com/path?a=1&b=2")

	def test_parse_body_json(self) -> None:
		content, headers = _parse_body(
			json_body={"x": 1},
			form=None,
			text=None,
			bytes_base64=None,
			content_type=None,
		)
		self.assertIsInstance(content, (bytes, bytearray))
		self.assertIn("application/json", headers.get("content-type", ""))

	def test_parse_body_form(self) -> None:
		content, headers = _parse_body(
			json_body=None,
			form={"a": "b"},
			text=None,
			bytes_base64=None,
			content_type=None,
		)
		self.assertEqual(content, b"a=b")
		self.assertIn("application/x-www-form-urlencoded", headers.get("content-type", ""))

	def test_parse_body_text_defaults_content_type(self) -> None:
		content, headers = _parse_body(
			json_body=None,
			form=None,
			text="hello",
			bytes_base64=None,
			content_type=None,
		)
		self.assertEqual(content, b"hello")
		self.assertIn("text/plain", headers.get("content-type", ""))

	def test_parse_body_bytes_base64_invalid(self) -> None:
		with self.assertRaises(ValueError):
			_parse_body(
				json_body=None,
				form=None,
				text=None,
				bytes_base64="not-base64",
				content_type="application/octet-stream",
			)

