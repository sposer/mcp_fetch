import unittest

from mcp_fetch.converter import html_to_markdown


class TestConverter(unittest.TestCase):
    def test_html_to_markdown_basic(self) -> None:
        out = html_to_markdown("<h1>Title</h1><p>Hello</p>")
        self.assertIn("Title", out)
        self.assertIn("Hello", out)
