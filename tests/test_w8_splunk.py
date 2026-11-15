"""The real Splunk adapter is fail closed and uses only fake transport here."""

import io
import unittest
import urllib.parse
from datetime import datetime, timezone

from egis_soc.w8_splunk import SplunkReadOnlyConfig, SplunkReadOnlySearch


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
LATER = datetime(2026, 1, 2, tzinfo=timezone.utc)


class W8SplunkTests(unittest.TestCase):
    def config(self, **changes):
        return SplunkReadOnlyConfig(**({
            "base_url": "https://splunk.example.invalid:8089", "token": "synthetic-token",
            "allowed_indexes": ("security",),
        } | changes))

    def test_disabled_default_and_invalid_config(self):
        adapter = SplunkReadOnlySearch(self.config(), lambda *a, **k: self.fail("network"))
        with self.assertRaises(PermissionError):
            adapter.search(index="security", host="WS01", earliest=NOW, latest=LATER)
        for change in ({"base_url": "http://example.invalid"},
                       {"allowed_indexes": ("security | delete",)},
                       {"max_events": 1000}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.config(**change)

    def test_allowlist_query_and_bounded_response(self):
        calls = []
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        def fake(request, timeout):
            calls.append((request, timeout))
            return Response(b'{"result":{"_raw":"synthetic"}}\n')
        adapter = SplunkReadOnlySearch(self.config(enabled=True, max_events=2), fake)
        for index, host in (("other", "WS01"), ("security", "WS01|delete")):
            with self.assertRaises(ValueError):
                adapter.search(index=index, host=host, earliest=NOW, latest=LATER)
        self.assertEqual(calls, [])
        self.assertEqual(len(adapter.search(index="security", host="WS01",
                                            earliest=NOW, latest=LATER)), 1)
        request, timeout = calls[0]
        self.assertEqual(request.full_url,
                         "https://splunk.example.invalid:8089/services/search/jobs/export")
        self.assertEqual(timeout, 15)
        query = urllib.parse.parse_qs(request.data.decode("ascii"))["search"][0]
        self.assertIn('index="security"', query)
        self.assertIn("| head 2", query)
        self.assertNotIn("outputlookup", query)

    def test_response_size_and_count_limits(self):
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        config = self.config(enabled=True, max_events=1)
        for body in (b"x" * 1_000_001,
                     b'{"result":{}}\n{"result":{}}\n',
                     b'{"error":"oops"}\n'):
            with self.subTest(length=len(body)), self.assertRaises(ValueError):
                SplunkReadOnlySearch(config, lambda *a, **k: Response(body)).search(
                    index="security", host="WS01", earliest=NOW, latest=LATER)


if __name__ == "__main__":
    unittest.main()
