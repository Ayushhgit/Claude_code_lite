import logging
import functools

logging.basicConfig(level=logging.INFO)

def cache_result(ttl=60):
    cache = {}
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = str(args) + str(kwargs)
            if key in cache:
                result, timestamp = cache[key]
                if time.time() - timestamp < ttl:
                    logging.info(f"Cache hit for {func.__name__} with args {args} and kwargs {kwargs}")
                    return result
            result = func(*args, **kwargs)
            cache[key] = (result, time.time())
            logging.info(f"Cache miss for {func.__name__} with args {args} and kwargs {kwargs}")
            return result
        return wrapper
    return decorator

import time

@cache_result(ttl=300)
def add(a, b):
    logging.info(f"Adding {a} and {b}")
    return a + b