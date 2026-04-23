import logging
import functools

logging.basicConfig(level=logging.INFO)

cache = {}

def cached(func):
    @functools.wraps(func)
    def wrapper(*args):
        if args in cache:
            logging.info(f"Cache hit for {func.__name__} with args {args}")
            return cache[args]
        result = func(*args)
        cache[args] = result
        logging.info(f"Cache miss for {func.__name__} with args {args}, result cached")
        return result
    return wrapper

@cached
def add(a, b):
    logging.info(f"Adding {a} and {b}")
    return a + b