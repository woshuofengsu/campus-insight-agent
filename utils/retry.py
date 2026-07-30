# utils/retry.py
import time
import functools
from utils.logger import get_logger

logger = get_logger(__name__)


def retry_on_failure(max_retries: int = 2):
    """Decorator: retry a function on exception with exponential backoff."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt+1}/{max_retries+1}): {e}. Retrying..."
                        )
                        time.sleep(2 ** attempt)
            logger.error(f"{func.__name__} failed after {max_retries+1} attempts: {last_error}")
            raise last_error
        return wrapper
    return decorator
