import signal
from threading import Thread
from timeit import default_timer


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
        print(f"Function {function.__name__} took {time_elapsed} ms")
        return return_value

    return _timeit


def run_in_thread(function):
    def _run_in_thread(*args, **kwargs):
        Thread(target=function, args=args, kwargs=kwargs).start()
        return

    return _run_in_thread


def notify_timeout(milliseconds: int):
    def _timeout(function):
        def wrapper(*args, **kwargs):
            start = default_timer()
            function(*args, **kwargs)
            end = default_timer()
            time_elapsed = (end - start) * 1000
            if time_elapsed >= milliseconds:
                print(f"[WARNING] {function.__name__} took {time_elapsed} ms")

        return wrapper

    return _timeout


class _SingletonWrapper:
    """
    A singleton wrapper class. Its instances would be created
    for each decorated class.
    """

    def __init__(self, cls):
        self.__wrapped__ = cls
        self._instance = None

    def __call__(self, *args, **kwargs):
        """Returns a single instance of decorated class"""
        if self._instance is None:
            self._instance = self.__wrapped__(*args, **kwargs)
        return self._instance


def singleton(cls):
    """
    A singleton decorator. Returns a wrapper objects. A call on that object
    returns a single instance object of decorated class. Use the __wrapped__
    attribute to access decorated class directly in unit tests
    """
    return _SingletonWrapper(cls)
