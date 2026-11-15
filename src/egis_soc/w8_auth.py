"""Single-owner local review authentication; bearer sessions live only in RAM."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,99}\Z")
_HASH = re.compile(r"scrypt-v1\$([0-9a-f]{32})\$([0-9a-f]{64})\Z")
_N, _R, _P = 2**14, 8, 1


def make_password_hash(password: str, *, salt: bytes | None = None) -> str:
    """Generate an environment-safe verifier; never store the password itself."""
    if type(password) is not str or not 12 <= len(password) <= 1024:
        raise ValueError("review_password_length")
    salt = secrets.token_bytes(16) if salt is None else salt
    if type(salt) is not bytes or len(salt) != 16:
        raise ValueError("review_salt_length")
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt-v1${salt.hex()}${digest.hex()}"


@dataclass(frozen=True)
class ReviewIdentity:
    reviewer_id: str
    password_hash: str
    session_seconds: int = 900

    def __post_init__(self) -> None:
        if (type(self.reviewer_id) is not str
                or not _IDENTIFIER.fullmatch(self.reviewer_id)
                or type(self.password_hash) is not str
                or not _HASH.fullmatch(self.password_hash)
                or type(self.session_seconds) is not int
                or not 60 <= self.session_seconds <= 3600):
            raise ValueError("invalid_local_review_identity")

    @classmethod
    def from_environment(cls) -> ReviewIdentity | None:
        reviewer = os.environ.get("EGIS_REVIEWER_ID")
        verifier = os.environ.get("EGIS_REVIEW_PASSWORD_HASH")
        if reviewer is None and verifier is None:
            return None
        if reviewer is None or verifier is None:
            raise ValueError("incomplete_review_environment")
        try:
            seconds = int(os.environ.get("EGIS_REVIEW_SESSION_SECONDS", "900"))
        except ValueError:
            raise ValueError("invalid_review_session_seconds") from None
        return cls(reviewer, verifier, seconds)

    def check_password(self, password: str) -> bool:
        if type(password) is not str or len(password) > 1024:
            return False
        match = _HASH.fullmatch(self.password_hash)
        if match is None:
            return False
        salt = bytes.fromhex(match.group(1))
        expected = bytes.fromhex(match.group(2))
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                n=_N, r=_R, p=_P, dklen=32)
        return hmac.compare_digest(actual, expected)


class ReviewSessions:
    def __init__(self, identity: ReviewIdentity,
                 clock: Callable[[], float] = time.monotonic):
        self.identity = identity
        self.clock = clock
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()

    def login(self, password: str) -> str:
        if not self.identity.check_password(password):
            raise PermissionError("invalid_review_credentials")
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = self.clock() + self.identity.session_seconds
        return token

    def reviewer(self, token: str) -> str:
        if type(token) is not str or len(token) > 256:
            raise PermissionError("invalid_review_session")
        with self._lock:
            expiry = self._sessions.get(token)
            if expiry is None or expiry <= self.clock():
                self._sessions.pop(token, None)
                raise PermissionError("expired_or_unknown_review_session")
        return self.identity.reviewer_id

    def logout(self, token: str) -> None:
        self.reviewer(token)
        with self._lock:
            self._sessions.pop(token, None)
