import pytest
from app.core.llm.retry import with_backoff


class RetryableError(Exception):
    pass


class FatalError(Exception):
    pass


def test_retries_until_success_within_max_retries():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RetryableError("try again")
        return "ok"

    result = with_backoff(
        flaky, is_retryable=lambda e: isinstance(e, RetryableError),
        max_retries=5, base_delay=0.01, max_delay=0.05, sleep=lambda s: None,
    )

    assert result == "ok"
    assert attempts["count"] == 3


def test_raises_immediately_on_non_retryable_error():
    def always_fatal():
        raise FatalError("nope")

    with pytest.raises(FatalError):
        with_backoff(
            always_fatal, is_retryable=lambda e: isinstance(e, RetryableError),
            max_retries=5, base_delay=0.01, sleep=lambda s: None,
        )


def test_raises_after_exhausting_max_retries():
    def always_retryable():
        raise RetryableError("still failing")

    with pytest.raises(RetryableError):
        with_backoff(
            always_retryable, is_retryable=lambda e: isinstance(e, RetryableError),
            max_retries=3, base_delay=0.01, sleep=lambda s: None,
        )
