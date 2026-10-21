"""The web password: hashing, checking, and the limit on guesses."""

import pytest

from resume_maxer.auth import HashFormatError, LoginLimiter, hash_password, verify_password


def test_right_password_verifies_and_wrong_one_does_not():
    stored = hash_password("correct horse battery")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("correct horse batterY", stored)
    assert not verify_password("", stored)


def test_hash_never_contains_the_password_and_salts_differ():
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert "correct" not in first
    assert first != second  # a fresh salt each time
    assert first.startswith("scrypt$")


@pytest.mark.parametrize("stored", ["", "plaintext", "md5$x$y", "scrypt$1$2$3$!!$!!"])
def test_malformed_hash_is_a_configuration_error_not_a_pass(stored):
    with pytest.raises(HashFormatError, match="hash-password"):
        verify_password("anything", stored)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_limiter_blocks_after_the_limit_and_forgets_after_the_window():
    clock = Clock()
    limiter = LoginLimiter(limit=3, window_s=60, clock=clock)
    for _ in range(2):
        limiter.record_failure("1.2.3.4")
    assert not limiter.blocked("1.2.3.4")  # under the limit: still allowed
    limiter.record_failure("1.2.3.4")
    assert limiter.blocked("1.2.3.4")
    assert not limiter.blocked("5.6.7.8")  # one visitor's guesses never lock out another
    clock.now += 61
    assert not limiter.blocked("1.2.3.4")


def test_successful_login_resets_the_count():
    limiter = LoginLimiter(limit=2, window_s=60, clock=Clock())
    limiter.record_failure("1.2.3.4")
    limiter.reset("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    assert not limiter.blocked("1.2.3.4")
