from pathlib import Path, PurePath
from datetime import datetime
import collections
import sys
import os
import json
import subprocess
import logging
import time
import socket
import asyncio
from math import inf


def as_dict(par):
    if not par or isinstance(par, dict):
        return par
    else:
        return dict(par._asdict())


def from_dict(par_dict):
    if not par_dict:
        return None
    par = collections.namedtuple('Params', par_dict.keys())

    class IBLParams(par):
        __slots__ = ()

        def set(self, field, value):
            d = as_dict(self)
            d[field] = value
            return from_dict(d)

        def as_dict(self):
            return as_dict(self)

    return IBLParams(**par_dict)


def getfile(str_params):
    """
    Returns full path of the param file per system convention:
     linux/mac: ~/.str_params, Windows: APPDATA folder

    :param str_params: string that identifies parm file
    :return: string of full path
    """
    # strips already existing dot if any
    parts = ['.' + p if not p.startswith('.') else p for p in Path(str_params).parts]
    if sys.platform == 'win32' or sys.platform == 'cygwin':
        pfile = str(PurePath(os.environ['APPDATA'], *parts))
    else:
        pfile = str(Path.home().joinpath(*parts))
    return pfile


def set_hidden(path, hide: bool) -> Path:
    """
    Set a given file or folder path to be hidden.  On macOS and Windows a specific flag is set,
    while on other systems the file or folder is simply renamed to start with a dot.  On macOS the
    folder may only be hidden in Explorer.

    Parameters
    ----------
    path : str, pathlib.Path
        The path of the file or folder to (un)hide.
    hide : bool
        If True the path is set to hidden, otherwise it is unhidden.

    Returns
    -------
    pathlib.Path
        The path of the file or folder, which may have been renamed.
    """
    path = Path(path)
    assert path.exists()
    if sys.platform == 'win32' or sys.platform == 'cygwin':
        flag = ('+' if hide else '-') + 'H'
        subprocess.run(['attrib', flag, str(path)]).check_returncode()
    elif sys.platform == 'darwin':
        flag = ('' if hide else 'no') + 'hidden'
        subprocess.run(['chflags', flag, str(path)]).check_returncode()
    elif hide and not path.name.startswith('.'):
        path = path.rename(path.parent.joinpath('.' + path.name))
    elif not hide and path.name.startswith('.'):
        path = path.rename(path.parent.joinpath(path.name[1:]))
    return path


def read(str_params, default=None):
    """
    Reads in and parse Json parameter file into dictionary.  If the parameter file doesn't
    exist and no defaults are provided, a FileNotFound error is raised, otherwise any extra
    default parameters will be written into the file.

    Examples:
        # Load parameters, raise error if file not found
        par = read('globus/admin')

        # Load with defaults
        par = read('globus/admin', {'local_endpoint': None, 'remote_endpoint': None})

        # Return empty dict if file not found (i.e. touch new param file)
        par = read('new_pars', {})

    :param str_params: path to text json file
    :param default: default values for missing parameters
    :return: named tuple containing parameters
    """
    pfile = getfile(str_params)
    par_dict = as_dict(default) or {}
    if Path(pfile).exists():
        with open(pfile) as fil:
            file_pars = json.loads(fil.read())
        par_dict.update(file_pars)
    elif default is None:  # No defaults provided
        raise FileNotFoundError(f'Parameter file {pfile} not found')

    if not Path(pfile).exists() or par_dict.keys() > file_pars.keys():
        # write the new parameter file with the extra param
        write(str_params, par_dict)
    return from_dict(par_dict)


def write(str_params, par):
    """
    Write a parameter file in Json format

    :param str_params: path to text json file
    :param par: dictionary containing parameters values
    :return: None
    """
    pfile = Path(getfile(str_params))
    if not pfile.parent.exists():
        pfile.parent.mkdir()
    dpar = as_dict(par)
    for k in dpar:
        if isinstance(dpar[k], Path):
            dpar[k] = str(dpar[k])
    with open(pfile, 'w') as fil:
        json.dump(as_dict(par), fil, sort_keys=False, indent=4)


class FileLock:
    def __init__(self, filename, log=None, timeout=10, timeout_action='delete'):
        self.filename = Path(filename)
        self._logger = log or logging.getLogger(__name__)
        self.timeout = timeout
        self.timeout_action = timeout_action
        if not self.timeout_action in ('delete', 'raise'):
            raise ValueError(f'Invalid timeout action: {self.timeout_action}')
        self._poll_freq = 0.2

    @property
    def lockfile(self):
        return self.filename.with_suffix('.lock')

    async def _lock_check_async(self):
        while self.lockfile.exists():
            await asyncio.sleep(self._poll_freq)

    def __enter__(self):
        # if a lock file exists retries n times to see if it exists
        attempts = 0
        n_attempts = 5 if self.timeout else inf
        timeout = self.timeout / n_attempts if self.timeout else self._poll_freq

        while self.lockfile.exists() or attempts <= n_attempts:
            self._logger.info('file lock found, waiting %.2f seconds %s', timeout, self.lockfile)
            time.sleep(timeout)
            attempts += 1

        # if the file still exists after 5 attempts, remove it as it's a job that went wrong
        if self.lockfile.exists():
            with open(self.lockfile, 'r') as fp:
                self._logger.debug('file lock contents: %s', json.load(fp))
            if self.timeout_action == 'delete':
                self._logger.info('stale file lock found, deleting %s', self.lockfile)
                self.lockfile.unlink()
            else:
                raise TimeoutError(f'{self.lockfile} file lock timed out')

        # add in the lock file, add some metadata to ease debugging if one gets stuck
        with open(self.lockfile, 'w') as fp:
            json.dump(dict(datetime=datetime.utcnow().isoformat(), hostname=str(socket.gethostname)), fp)

    async def __aenter__(self):
        # if a lock file exists wait until timeout before removing
        try:
            await asyncio.wait_for(self._lock_check_async(), timeout=self.timeout)
        except asyncio.TimeoutError as e:
            with open(self.lockfile, 'r') as fp:
                self._logger.debug('file lock contents: %s', json.load(fp))
            if self.timeout_action == 'raise':
                raise e
            self._logger.info('stale file lock found, deleting %s', self.lockfile)
            self.lockfile.unlink()

        # add in the lock file, add some metadata to ease debugging if one gets stuck
        with open(self.lockfile, 'w') as fp:
            json.dump(dict(datetime=datetime.utcnow().isoformat(), hostname=str(socket.gethostname)), fp)

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.lockfile.unlink()

    async def __aexit__(self, exc_type, exc_value, exc_tb):
        self.lockfile.unlink()
