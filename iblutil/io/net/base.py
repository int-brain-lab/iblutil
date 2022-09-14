"""
Protocol
--------
EXPINIT
    Experiment is initializing.
EXPSTART
    Experiment has begun.
EXPEND
    Experiment has stopped.
EXPCLEANUP
    Experiment cleanup begun.
EXPINTERUPT
    Experiment interrupted.
EXPSTATUS
    Experiment status.
EXPINFO
    Experiment info.
ALYX
    Alyx token.
"""
import re
import json
import socket
import warnings
from asyncio import isfuture
from abc import ABC, abstractmethod
from urllib.parse import urlparse
import urllib.request
import ipaddress


LISTEN_PORT = 1001  # listen for commands on this port


def external_ip():
    return urllib.request.urlopen('https://ident.me').read().decode('utf8')


def is_valid_ip(ip_address):
    try:
        ipaddress.ip_address(ip_address)
        return True
    except ValueError:
        return False


def hostname2ip(hostname=None):
    hostname = hostname or socket.gethostname()
    try:
        ip_address = socket.gethostbyname(hostname)
        return ipaddress.ip_address(ip_address)
    except (socket.error, socket.gaierror):
        raise ValueError(f'Failed to resolve IP for hostname "{hostname}"')


def validate_uri(uri, resolve_host=True, default_port=LISTEN_PORT, default_proc='udp'):
    # Validate URI scheme
    if not isinstance(uri, (str, ipaddress.IPv4Address, ipaddress.IPv6Address)):
        raise TypeError(f'Unsupported URI "{uri}" of type {type(uri)}')

    if isinstance(uri, str) and (proc := re.match(r'(?P<proc>^[a-zA-Z]+(?=://))', uri)):
        proc = proc.group()
        uri = uri[len(proc) + 3:]
    else:
        proc = default_proc
    # Validate hostname
    if isinstance(uri, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        host = str(uri)
        port = default_port
    elif ':' in uri:
        host, port = uri.split(':', 1)
    else:
        host = uri
        port = None
    if isinstance(uri, str) and not is_valid_ip(host):
        if resolve_host:
            host = hostname2ip(host)
        elif not re.match(r'^[a-z0-9-]+$', host):
            raise ValueError(f'Invalid hostname "{host}"')
    # Validate port
    try:
        port = int(port or default_port)
        assert 1 <= port <= 65535
    except (AssertionError, ValueError):
        raise ValueError(f'Invalid port number: {port or default_port}')
    return f'{proc or default_proc}://{host}:{port}'


class Communicator(ABC):
    default_listen_port = LISTEN_PORT
    event_mode = False
    server_uri = None
    _callbacks = {k: [] for k in ('EXPINIT', 'EXPSTART', 'EXPEND', 'EXPCLEANUP')}

    def assign_callback(self, event, callback):
        if (event := event.strip().upper()) not in self._callbacks:
            raise ValueError(f'Unrecognized event "{event}". Choices: {tuple(self._callbacks.keys())}')
        if not (callable(callback) or isfuture(callback)):
            raise ValueError('Callback must be callable or a Future')
        self._callbacks.setdefault(event, []).append(callback)

    @property
    def port(self) -> int:
        return urlparse(self.server_uri).port

    @property
    def hostname(self) -> str:
        return urlparse(self.server_uri).hostname

    @property
    def protocol(self) -> str:
        return urlparse(self.server_uri).scheme

    @property
    @abstractmethod
    def is_connected(self):
        pass

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def send(self, data):
        pass

    @abstractmethod
    def receive(self, data, addr):
        pass

    @abstractmethod
    def cleanup(self):
        pass

    @staticmethod
    def encode(data):
        """Serialize data for transmission"""
        if isinstance(data, bytes):
            return data
        if not isinstance(data, str):
            data = json.dumps(data)
        return data.encode()

    @staticmethod
    def decode(data):
        """Serialize data for transmission"""
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            warnings.warn('Failed to decode as JSON')
            data = data.decode()
        return data
