import signal


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
