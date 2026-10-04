"""Small, ordered work queue: never submit the whole paid corpus ahead of validation."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor


def ordered_map(function, items, *, workers=1):
    if not 1 <= workers <= 4:
        raise ValueError("Workers must be between 1 and 4")
    if workers == 1:
        yield from map(function, items)
        return
    iterator, sentinel = iter(items), object()
    executor = ThreadPoolExecutor(max_workers=workers)
    pending = deque()
    try:
        for _ in range(workers):
            if (item := next(iterator, sentinel)) is not sentinel:
                pending.append(executor.submit(function, item))
        while pending:
            yield pending.popleft().result()
            if (item := next(iterator, sentinel)) is not sentinel:
                pending.append(executor.submit(function, item))
    finally:
        # After an error, at most workers-1 in-flight requests can complete. No unbounded paid queue.
        executor.shutdown(wait=True, cancel_futures=True)
