"""Opt-in, bounded Splunk search transport; no real-data admission or writes.

Returned bytes need separate source authorization, custody, identity and W2
ingestion before they can become EGIS-SOC evidence. The W8 demo never calls this.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


@dataclass(frozen=True)
class SplunkReadOnlyConfig:
    base_url: str
    token: str
    allowed_indexes: tuple[str, ...]
    timeout_seconds: int = 15
    max_events: int = 50
    enabled: bool = False

    def __post_init__(self):
        url = urllib.parse.urlparse(self.base_url)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in {"", "/"}
                or not self.token or any(c.isspace() for c in self.token)
                or not self.allowed_indexes or len(set(self.allowed_indexes)) != len(self.allowed_indexes)
                or any(not _NAME.fullmatch(index) for index in self.allowed_indexes)
                or type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 30
                or type(self.max_events) is not int or not 1 <= self.max_events <= 100
                or type(self.enabled) is not bool):
            raise ValueError("invalid_read_only_splunk_config")


class SplunkReadOnlySearch:
    def __init__(self, config: SplunkReadOnlyConfig,
                 opener: Callable | None = None):
        self.config = config
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({})).open

    def search(self, *, index: str, host: str,
               earliest: datetime, latest: datetime) -> tuple[dict, ...]:
        config = self.config
        if not config.enabled:
            raise PermissionError("real_splunk_mode_disabled")
        if (index not in config.allowed_indexes or not _HOST.fullmatch(host)
                or earliest.tzinfo is None or latest.tzinfo is None
                or earliest >= latest):
            raise ValueError("splunk_search_outside_allowlist")
        start = earliest.astimezone(timezone.utc).isoformat()
        end = latest.astimezone(timezone.utc).isoformat()
        # The caller supplies only validated values, never raw SPL.
        search = (f'search index="{index}" host="{host}" '
                  'sourcetype="XmlWinEventLog" (EventCode=4624 OR EventCode=4625 OR EventCode=1) '
                  f'earliest="{start}" latest="{end}" '
                  f'| head {config.max_events}')
        body = urllib.parse.urlencode({"search": search, "output_mode": "json",
                                      "count": config.max_events}).encode("ascii")
        request = urllib.request.Request(
            config.base_url.rstrip("/") + "/services/search/jobs/export",
            data=body, method="POST",
            headers={"Authorization": "Bearer " + config.token,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.opener(request, timeout=config.timeout_seconds) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("splunk_response_limit")
        rows = []
        for line in raw.splitlines():
            if not line:
                continue
            item = json.loads(line)
            if type(item) is not dict or set(item) != {"result"} or type(item["result"]) is not dict:
                raise ValueError("invalid_splunk_export_row")
            rows.append(item)
            if len(rows) > config.max_events:
                raise ValueError("splunk_event_limit")
        return tuple(rows)
