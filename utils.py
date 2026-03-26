import time
from functools import wraps


def retry(max_attempts=3, delay=1, backoff=2, exceptions=(Exception,)):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_error = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_error = e

                    if attempt == max_attempts:
                        raise

                    print(
                        f"[retry] {func.__name__} failed on attempt {attempt}/{max_attempts}: {e}. "
                        f"Retrying in {current_delay}s..."
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff

            raise last_error

        return wrapper
    return decorator