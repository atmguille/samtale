import logging

LEVELS = {'debug': logging.DEBUG,
          'info': logging.INFO,
          'warning': logging.WARNING,
          'error': logging.ERROR,
          'critical': logging.CRITICAL,
          'not set': logging.NOTSET}


def set_logger(args):
    """
    Sets log level and format
    :param args: arguments received from command line
    :return: set logger
    """
    level = LEVELS.get(args.log_level, logging.NOTSET)
    str_format = '%(asctime)s [%(levelname)s] - %(message)s'
    logging.basicConfig(level=level, format=str_format)
    return logging.getLogger(__name__)


def get_logger():
    """
    :return: logger of the running program
    """
    return logging.getLogger(__name__)
