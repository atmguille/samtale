import signal
from timeit import default_timer
from practica3_client import POLLING_TIME


def timeout(milliseconds: int):
    class _TimeoutException(Exception):
        pass

    def _handler(signum, frame):
        raise _TimeoutException()

    def _timeout(function):
        def wrapper(*args, **kwargs):
            original_handler = signal.signal(signal.SIGALRM, _handler)
            signal.setitimer(signal.ITIMER_REAL, milliseconds / 1000)

            try:
                function(*args, **kwargs)
            except _TimeoutException:
                pass
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, original_handler)

        return wrapper

    return _timeout


def timer(function):
    def _timeit(*args, **kwargs):
        start = default_timer()
        return_value = function(*args, **kwargs)
        end = default_timer()
        time_elapsed = (end - start) * 1000

        if time_elapsed >= POLLING_TIME:
            print(f"Function {function.__name__} took {time_elapsed} ms")
        return return_value

    return _timeit
