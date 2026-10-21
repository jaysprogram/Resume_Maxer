"""The web app's single password: hashing, checking, and slowing down guessing.

The password itself is never stored. Its scrypt hash lives in an environment
variable, produced by `resume-maxer hash-password`.
"""

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable

# scrypt cost: ~0.1 s and 32 MB per check on a small server, which makes offline
# guessing expensive while a person logging in never notices.
_N, _R, _P = 2**15, 8, 1
_MAXMEM = 64 * 1024 * 1024


class HashFormatError(ValueError):
    """The configured password hash is not one hash_password made."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """'scrypt$N$r$p$salt$hash', safe to keep in an environment variable."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32
    )
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            raise ValueError(scheme)
        expected = base64.b64decode(digest, validate=True)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt, validate=True),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=_MAXMEM,
            dklen=len(expected),
        )
    except ValueError as exc:  # includes binascii.Error from bad base64
        raise HashFormatError(
            "the password hash is malformed; make a new one with `resume-maxer hash-password`"
        ) from exc
    return hmac.compare_digest(actual, expected)


class LoginLimiter:
    """At most `limit` failed logins per client in a sliding `window_s`."""

    def __init__(
        self,
        limit: int = 5,
        window_s: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, client: str) -> deque[float]:
        failures, cutoff = self._failures[client], self.clock() - self.window_s
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures

    def blocked(self, client: str) -> bool:
        return len(self._recent(client)) >= self.limit

    def record_failure(self, client: str) -> None:
        self._recent(client).append(self.clock())

    def reset(self, client: str) -> None:
        self._failures.pop(client, None)
