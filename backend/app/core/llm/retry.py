import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def with_backoff(
    fn: Callable[[], T],
    is_retryable: Callable[[Exception], bool],
    max_retries: int = 5,
    base_delay: float = 10.0,
    max_delay: float = 120.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call fn(), retrying with exponential backoff + jitter on retryable errors."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == max_retries - 1 or not is_retryable(exc):
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay += random.uniform(0, delay * 0.1)
            sleep(delay)
    raise RuntimeError("unreachable")
