from pathlib import Path
import collections
import colorlog
import logging
import sys

import numpy as np

LOG_FORMAT_STR = '%(asctime)s.%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


class Bunch(dict):
    """A subclass of dictionary with an additional dot syntax."""

    def __init__(self, *args, **kwargs):
        super(Bunch, self).__init__(*args, **kwargs)
        self.__dict__ = self

    def copy(self):
        """Return a new Bunch instance which is a copy of the current Bunch instance."""
        return Bunch(super(Bunch, self).copy())

    def save(self, npz_file, compress=False):
        """
        Saves a npz file containing the arrays of the bunch.

        :param npz_file: output file
        :param compress: bool (False) use compression
        :return: None
        """
        if compress:
            np.savez_compressed(npz_file, **self)
        else:
            np.savez(npz_file, **self)

    @staticmethod
    def load(npz_file):
        """
        Loads a npz file containing the arrays of the bunch.

        :param npz_file: output file
        :return: Bunch
        """
        if not Path(npz_file).exists():
            raise FileNotFoundError(f"{npz_file}")
        return Bunch(np.load(npz_file))


def _iflatten(x):
    result = []
    for el in x:
        if isinstance(el, collections.abc.Iterable) and not (
                isinstance(el, str) or isinstance(el, dict)):
            result.extend(_iflatten(el))
        else:
            result.append(el)
    return result


def _gflatten(x):
    def iselement(e):
        return not (isinstance(e, collections.abc.Iterable) and not (
            isinstance(el, str) or isinstance(el, dict)))
    for el in x:
        if iselement(el):
            yield el
        else:
            yield from _gflatten(el)


def flatten(x, generator=False):
    """
    Flatten a nested Iterable excluding strings and dicts.

    Converts nested Iterable into flat list. Will not iterate through strings or
    dicts.

    :return: Flattened list or generator object.
    :rtype: list or generator
    """
    return _gflatten(x) if generator else _iflatten(x)


def range_str(values: iter) -> str:
    """
    Given a list of integers, returns a terse string expressing the unique values.

    Example:
        indices = [0, 1, 2, 3, 4, 7, 8, 11, 15, 20]
        range_str(indices)
        >> '0-4, 7-8, 11, 15 & 20'
    :param values: An iterable of ints
    :return: A string of unique value ranges
    """
    trial_str = ''
    values = list(set(values))
    for i in range(len(values)):
        if i == 0:
            trial_str += str(values[i])
        elif values[i] - (values[i - 1]) == 1:
            if i == len(values) - 1 or values[i + 1] - values[i] > 1:
                trial_str += f'-{values[i]}'
        else:
            trial_str += f', {values[i]}'
    # Replace final comma with an ampersand
    k = trial_str.rfind(',')
    if k > -1:
        trial_str = f'{trial_str[:k]} &{trial_str[k + 1:]}'
    return trial_str


def get_logger(name='ibl', level=logging.INFO, file=None, no_color=False):
    """
    Logger to use by default. Sets the name if not set already and add a stream handler
    If the stream handler already exists, does not duplicate.
    Uses date time, calling function and distinct colours for levels.
    The naming/level allows not to interfere with third-party libraries when setting level

    :param name: logger name, should be set to __name__ for consistent logging in the app
    :param level: defaults to INFO
    :param file: if not None, will add a File Handler
    :param no_color: if set to True, removes colorlogs. This is useful when stdout is redirected
     to a file
    :return: logger object
    """
    if not name:
        log = logging.getLogger()  # root logger
    else:
        log = logging.getLogger(name)
    colors = {'DEBUG': 'green',
              'INFO': 'cyan',
              'WARNING': 'bold_yellow',
              'ERROR': 'bold_red',
              'CRITICAL': 'bold_purple'}
    log.setLevel(level)
    fkwargs = {'no_color': True} if no_color else {'log_colors': colors}
    # check existence of stream handlers before adding another
    if not any(map(lambda x: x.name == f'{name}_auto', log.handlers)):
        stream_handler = logging.StreamHandler(stream=sys.stdout)
        stream_handler.setFormatter(
            colorlog.ColoredFormatter('%(log_color)s' + LOG_FORMAT_STR,
                                      LOG_DATE_FORMAT, **fkwargs))
        stream_handler.name = f'{name}_auto'
        stream_handler.setLevel(level)
        log.addHandler(stream_handler)
    # add the file handler if requested, but check for duplicates
    if not any(map(lambda x: x.name == f'{name}_file', log.handlers)):
        if file is True:
            log_to_file(name=name, level=level)
        elif file is not None:
            log_to_file(filename=file, name=name, level=level)
    return log


def log_to_file(filename=None, name='ibllib', level=logging.INFO):
    """
    Save log information to a given filename in '.ibl_logs' folder (in home directory).

    Parameters
    ----------
    full_file_path : str or Pathlib.Path
        The name of the log file to save to.
    log : str, logging.Logger
        The log (name or object) to add file handler to.

    Returns
    -------
    logging.Logger
        The log with the file handler attached.
    """
    if filename is None:
        filename = Path.home().joinpath('.ibl_logs', name)
    elif not Path(filename).is_absolute():
        filename = Path.home().joinpath('.ibl_logs', filename)
    filename.parent.mkdir(exist_ok=True)
    if isinstance(name, str):
        log = logging.getLogger(name)
    log.setLevel(level)
    file_handler = logging.FileHandler(filename)
    file_format = logging.Formatter(LOG_FORMAT_STR, LOG_DATE_FORMAT)
    file_handler.setFormatter(file_format)
    file_handler.name = f"{name}_file"
    log.addHandler(file_handler)
    log.info(f'File log initiated {file_handler.name}')
    return log
