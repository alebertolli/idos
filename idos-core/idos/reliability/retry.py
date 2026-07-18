import time
import random
from functools import wraps
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def retry_with_backoff(
    max_attempts: int = 5,
    initial_delay: float = 2.0,
    max_delay: float = 16.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (ConnectionError, TimeoutError, IOError, OSError),
):
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        raise
                    actual_delay = delay
                    if jitter:
                        actual_delay = delay * (0.5 + random.random() * 0.5)
                    time.sleep(actual_delay)
                    delay = min(delay * backoff_factor, max_delay)
            raise last_exception
        return wrapper
    return decorator


def execute_with_retry(
    func: Callable[..., Any],
    args: tuple = (),
    kwargs: dict[str, Any] | None = None,
    max_attempts: int = 5,
    initial_delay: float = 2.0,
    max_delay: float = 16.0,
    backoff_factor: float = 2.0,
) -> tuple[bool, Any, list[dict[str, Any]]]:
    attempts_log: list[dict[str, Any]] = []
    delay = initial_delay
    last_exception = None
    kwargs = kwargs or {}

    for attempt in range(1, max_attempts + 1):
        try:
            result = func(*args, **kwargs)
            attempts_log.append({"attempt": attempt, "status": "SUCCESS"})
            return True, result, attempts_log
        except Exception as e:
            last_exception = e
            attempts_log.append({"attempt": attempt, "status": "FAILED", "error": str(e)})
            if attempt == max_attempts:
                break
            actual_delay = delay * (0.5 + random.random() * 0.5)
            time.sleep(actual_delay)
            delay = min(delay * backoff_factor, max_delay)

    return False, last_exception, attempts_log
