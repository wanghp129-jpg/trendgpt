from __future__ import annotations

import unittest
from urllib.request import Request

from trendgpt.adapters.http import (
    SourceFetchError, _AllowlistRedirectHandler, _allowed_url, get_public_text,
)


class PublicHttpSafetyTests(unittest.TestCase):
    def test_only_allowlisted_https_hosts_are_accepted(self):
        self.assertTrue(_allowed_url("https://store.steampowered.com/search/"))
        self.assertFalse(_allowed_url("http://store.steampowered.com/search/"))
        self.assertFalse(_allowed_url("https://evil.example/"))
        self.assertFalse(_allowed_url("https://www.youtube.com.evil.example/"))

    def test_initial_unallowlisted_url_is_rejected_before_network(self):
        with self.assertRaises(SourceFetchError) as caught:
            get_public_text("https://evil.example/")
        self.assertEqual(caught.exception.code, "host_not_allowed")

    def test_redirect_to_unallowlisted_host_is_rejected(self):
        handler = _AllowlistRedirectHandler()
        request = Request("https://store.steampowered.com/search/")
        with self.assertRaises(SourceFetchError) as caught:
            handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/collect")
        self.assertEqual(caught.exception.code, "redirect_host_not_allowed")

    def test_redirect_within_allowlist_is_permitted(self):
        handler = _AllowlistRedirectHandler()
        request = Request("https://store.steampowered.com/search/")
        redirected = handler.redirect_request(
            request, None, 302, "Found", {}, "https://store.steampowered.com/search/?page=2",
        )
        self.assertIsNotNone(redirected)
        self.assertEqual(redirected.full_url, "https://store.steampowered.com/search/?page=2")

    def test_nonpositive_limits_are_rejected(self):
        with self.assertRaises(SourceFetchError) as caught:
            get_public_text("https://store.steampowered.com/search/", timeout=0)
        self.assertEqual(caught.exception.code, "invalid_limit")


if __name__ == "__main__":
    unittest.main()
