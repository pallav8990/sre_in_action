from functools import wraps

def log_execution(logger):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger.info(f"Calling: {func.__name__} | args={args} kwargs={kwargs}")
            try:
                result = func(*args, **kwargs)
                logger.info(f"Returned: {func.__name__} => {result}")
                return result
            except Exception as e:
                logger.exception(f"Error in {func.__name__}: {e}")
                raise
        return wrapper
    return decorator