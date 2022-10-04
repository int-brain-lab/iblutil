"""
Examples
--------

# Connect to remote server rig, send initialization message and wait for response
>>> server = await EchoProtocol.server('udp://192.168.0.4', name='main')
>>> await server.init('2022-01-01_1_subject')  # Send init message and await confirmation of receipt
>>> response = await server.on_event('INIT')  # Await response

# Send initialization message and wait max 10 seconds for response
>>> try:
...     response = await asyncio.wait_for(server.on_event('INIT'), 10.)
... except asyncio.TimeoutError:
...     server.close()
"""

import json
import urllib.parse
import urllib.request
import logging
import asyncio
import argparse
import socket
from types import MappingProxyType
from collections import UserDict
from functools import partial

from iblutil.io.net.base import Communicator, LISTEN_PORT, validate_uri, hostname2ip, ExpMessage

### REMOVE ###
from iblutil.util import get_logger
_logger = get_logger(__name__, logging.DEBUG)
# _logger = logging.getLogger(__name__)
# _logger.setLevel(logging.DEBUG)

def _address2tuple(address) -> (str, int):
    """Convert URI to (host, port) tuple.

    Convert URI to form used by transport layer.

    Parameters
    ----------
    address : str
        A URI from which to extract the port and hostname.

    Returns
    -------
    str
        The hostname.
    int
        The port.
    """
    server_uri = validate_uri(address, default_port=LISTEN_PORT)
    parsed_uri = urllib.parse.urlparse(server_uri)
    return parsed_uri.hostname, parsed_uri.port


class EchoProtocol(Communicator):
    """An echo server implementing TCP/IP and UDP"""

    """asyncio.Server: A network server instance if using TCP/IP"""
    Server = None
    _role = None
    """bytes: The last sent message when awaiting confirmation of receipt"""
    _last_sent = None
    """float: The default echo timeout"""
    default_echo_timeout = 10.

    def __init__(self, server_uri, role, name=None):
        self._transport = None
        self._socket = None
        self.role = role
        self.server_uri = server_uri
        self.name = name or self.server_uri
        # For validating echo'd response
        self._last_sent = None
        self._echo_future = None
        # Transport specific futures
        loop = asyncio.get_running_loop()
        self.on_connection_lost = loop.create_future()
        self.on_error_received = loop.create_future()
        self.on_eof_received = loop.create_future()

    @property
    def role(self) -> str:
        """{'client', 'server'}: The remote computer's role"""
        return self._role

    @role.setter
    def role(self, value: str):
        """Set remote computer role.

        Ensures the role is only set once.

        Parameters
        ----------
        value : {'client', 'server'}
            The role to set.

        Raises
        ------
        AttributeError
            The role has already been set and cannot be changed.
        ValueError
            The role must be one of {'client', 'server'}.
        """
        if self._role is not None:
            raise AttributeError('can\'t set attribute')
        if value.strip().lower() not in ('server', 'client'):
            raise ValueError('role must be either "server" or "client"')
        self._role = value.strip().lower()

    @property
    def is_connected(self) -> bool:
        """bool: True if transport layer set and open."""
        return self._transport and not self._transport.is_closing()

    @property
    def awaiting_response(self) -> bool:
        """bool: True if awaiting confirmation of receipt from remote."""
        return self._last_sent and self._echo_future and not self._echo_future.done()

    async def cleanup(self, data=None):
        message = super().cleanup(data)
        await self.confirmed_send(message)

    async def start(self, exp_ref, data=None):
        message = super().start(exp_ref, data)
        await self.confirmed_send(message)

    async def stop(self, data=None, immediately=False):
        message = super().stop(data)
        await self.confirmed_send(message)

    async def init(self, data=None):
        """Initialize an experiment.

        Send an initialization message to the remote host.

        Parameters
        ----------
        data : any
            Optional extra data to send to the remote host.

        Raises
        ------
        TimeoutError
            Remote host failed to echo the message within the timeout period.
        """
        message = super().init(data)
        await self.confirmed_send(message)

    async def alyx(self, alyx=None):
        """
        Send/request Alyx token to/from remote host.

        Parameters
        ----------
        alyx : one.webclient.AlyxClient
            An instance of Alyx to extract and send token from.

        Returns
        -------
        (str, dict)
            (If alyx arg was None) the received Alyx token in the form (base_url, {user: token}).
        (str, int)
            The hostname and port of the remote host.
        """
        if alyx:  # send instance to remote host
            message = super().alyx(alyx)
            await self.confirmed_send(message)
        else:  # request instance from remote host
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            self.assign_callback('ALYX', fut)
            await self.confirmed_send(('ALYX', None))
            return fut

    @staticmethod
    def encode(data):
        """Serialize data for transmission"""
        if isinstance(data, bytes):
            return data
        if not isinstance(data, str):
            data = json.dumps(data)
        return data.encode()

    def send(self, data, addr=None):
        """Send data to clients.

        Serialize data and pass to transport layer.
        """
        _logger.debug(f'Send "{data}" to {self.server_uri}')
        if self.protocol == 'udp':
            self._transport.sendto(data, addr or (self.hostname, self.port))
        else:
            self._transport.write(self.encode(data))

    async def confirmed_send(self, data, timeout=None):
        """
        Send a message to the client and await echo.

        NB: Methods such as start, stop, init, cleanup and alyx should be used instead of calling
        this directly.

        Parameters
        ----------
        data : any
            The data to serialize and send to remote host.
        timeout : float, optional
            The time in seconds to wait for an echo before raising an exception.

        Raises
        ------
        TimeoutError
            Remote host failed to echo the message within the timeout period.
        RuntimeError
            The response from the client did not match the original message.
        ValueError
            Timeout must be non-zero number.
        """
        if not (timeout := timeout or self.default_echo_timeout) > 0:
            raise ValueError('Timeout must be non-zero number')
        self._last_sent = self.encode(data)
        self.send(self._last_sent)
        # Sockets can no longer be blocking, so we'll wait ourselves.
        try:
            loop = asyncio.get_running_loop()
            self._echo_future = loop.create_future()
            await asyncio.wait_for(self._echo_future, timeout=timeout)
        except asyncio.TimeoutError:
            self.close()
            raise TimeoutError('Failed to receive client response in time')
        except RuntimeError:
            self.close()
            raise RuntimeError('Unexpected response from server')
        self._echo_future = None
        _logger.debug('Confirmation received')

    def close(self):
        """
        Close the connection, de-register callbacks and cancel outstanding futures.

        The EchoProtocol.on_connection_lost future is resolved at this time, all others are
        cancelled.
        """
        # Close transport
        if self._transport:
            self._transport.close()

        super().close()  # Deregister callbacks, cancel event futures
        if self._echo_future and not self._echo_future.done():
            self._echo_future.cancel('Close called on communicator')
        if self.on_error_received:
            self.on_error_received.cancel('Close called on communicator')
        if self.on_eof_received:
            self.on_eof_received.cancel('Close called on communicator')
        if self.on_connection_lost and not self.on_connection_lost.done():
            self.on_connection_lost.set_result('Close called on communicator')

    # The following methods are inherited from asyncio.DatagramProtocol and called by the event loop

    def connection_made(self, transport):
        """Called by event loop"""
        self._transport = transport
        self._socket = transport.get_extra_info('socket')

        # Validate
        if self._socket.type is socket.SOCK_DGRAM:
            if self.protocol != 'udp':
                raise RuntimeError('Unsupported transport layer for UDP')
        elif self._socket.type is socket.SOCK_STREAM:
            if self.protocol not in ('ws', 'wss', 'tcp'):
                raise RuntimeError('Unsupported transport layer for TCP/IP')
        else:
            raise RuntimeError(f'Unsupported transport layer with socket type "{self._socket.type.name}"')
        _logger.debug(f'Connected with socket {self._socket}')

    def _receive(self, data, addr):
        """
        Process data received from remote host.  This is called by different lower level methods
        depending on the transport layer.  This method handles the message echo logic, while the
        base class method handles message callbacks exclusively.

        If awaiting an echo, the timeout is cancelled and the message is checked against the one
        sent.  Otherwise, the message is immediately echo'd and the super class method is called to
        notify any listeners.

        This method should not be called by the user.

        Parameters
        ----------
        data : bytes
            The serialized data received by the transport layer.
        addr : (str, int)
            The source address as (hostname, port)

        Notes
        -----
        Callbacks apply only to new messages, not echo responses.  EchoProtocol.confirmed_send
        should be awaited, however it is possible to assign a callback for receipt of an echo with
        EchoProtocol._echo_future.add_done_callback.

        """
        host, port = addr[:2]
        msg = data.decode()
        _logger.info('Received %r from %s://%s:%i', msg, self.protocol, host, port)
        if self.awaiting_response:
            # If echo doesn't match, raise exception
            if data != self._last_sent:
                _logger.error('Expected %s from %s, got %s', self._last_sent, self.name, data)
                self._echo_future.set_exception(RuntimeError)
            else:  # Notify callbacks of receipt
                self._echo_future.set_result(True)
        else:
            # Update from client
            _logger.debug('Send %r to %s://%s:%i', msg, self.protocol, host, port)
            self.send(data, addr)  # Echo
            super()._receive(data, addr)  # Process callbacks

    def datagram_received(self, data, addr):
        """Called by UDP transport layer"""
        host, port = addr[:2]
        if host != self.hostname:
            _logger.warning(f'Ignoring UDP packet from unexpected host ({host}:{port}) with message "{data}"')
        else:
            self._receive(data, addr)

    def data_received(self, data):
        """Called by TCP/IP transport layer"""
        addr = self._transport.get_extra_info('peername')[:2]
        self._receive(data, addr)

    def error_received(self, exc):
        _logger.error('Error received:', exc)
        self.on_error_received.set_result(exc)

    def eof_received(self):
        _logger.debug('EOF received')
        self.on_eof_received.set_result(True)

    def connection_lost(self, exc):
        _logger.info('Connection closed')
        if getattr(self, 'on_con_lost', False):
            self.on_connection_lost.set_result(exc)

    # Factory methods for instantiating a server or client

    @staticmethod
    async def server(server_uri, name=None, **kwargs) -> 'EchoProtocol':
        """
        Create a remote server instance.

        Parameters
        ----------
        server_uri : str
            The address of the remote computer, may be an IP or hostname with or without a port.
            To use TCP/IP instead of the default UDP, add a 'ws://' scheme to the URI.
        name : str
            An optional, arbitrary label.
        **kwargs
            Optional parameters to pass to create_datagram_endpoint for UDP or create_server for
            TCP/IP.

        Returns
        -------
        EchoProtocol
            A Communicator instance.
        """
        # Validate server URI
        server_uri = validate_uri(server_uri)

        # Get a reference to the event loop
        loop = asyncio.get_running_loop()

        # One protocol instance will be created to serve all client requests.
        if server_uri.startswith('udp'):
            Protocol = partial(EchoProtocol, server_uri, 'server', name=name)
            _, protocol = await loop.create_datagram_endpoint(Protocol, local_addr=_address2tuple(server_uri), **kwargs)
        else:
            protocol = EchoProtocol(server_uri, 'server', name=name)
            protocol.Server = await loop.create_server(lambda: protocol, *_address2tuple(server_uri), **kwargs)

        _logger.info(f'Listening on {protocol.server_uri}')
        return protocol

    @staticmethod
    async def client(server_uri, name=None, **kwargs) -> 'EchoProtocol':
        """
        Create a remote client instance.

        Parameters
        ----------
        server_uri : str
            The address of the remote computer, may be an IP or hostname with or without a port.
            To use TCP/IP instead of the default UDP, add a 'ws://' scheme to the URI.
        name : str
            An optional, arbitrary label.
        **kwargs
            Optional parameters to pass to create_datagram_endpoint for UDP or create_server for
            TCP/IP.

        Returns
        -------
        EchoProtocol
            A Communicator instance.
        """
        # Validate server URI
        server_uri = validate_uri(server_uri)

        # Get a reference to the event loop
        loop = asyncio.get_running_loop()

        Protocol = partial(EchoProtocol, server_uri, 'client', name=name)
        if server_uri.startswith('udp'):
            _, protocol = await loop.create_datagram_endpoint(Protocol, remote_addr=_address2tuple(server_uri), **kwargs)
        else:
            _, protocol = await loop.create_connection(Protocol, *_address2tuple(server_uri), **kwargs)

        return protocol


class Services(UserDict):
    """Handler for multiple remote rig services"""

    """MappingProxyType: map of rig names and their communicator"""
    _services = None

    def __init__(self, remote_rigs, alyx=None):
        """Handler for multiple remote rig services.

        Parameters
        ----------
        remote_rigs : list(iblutil.io.net.base.Communicator)
            A list of remote rig communicator objects.
        alyx : one.webclient.AlyxClient
            An optional Alyx instance to send on request.
        """
        # Store rig communicators by name
        super().__init__()
        self.data = MappingProxyType({rig.name: rig for rig in remote_rigs})  # Ensure immutable

        # Register callbacks so that if an Alyx instance is requested the provided token is sent.
        if alyx:
            for rig in self.values():
                rig.assign_callback(ExpMessage.ALYX, lambda _: rig.alyx(alyx))

    def assign_callback(self, event, callback, return_service=False):
        """
        Assign a callback to all services for a given event.

        Parameters
        ----------
        event : str, int, iblutil.io.net.base.ExpMessage
            An event to listen for.
        callback : function, async.io.Future
            A callable or future to notify when the event occurs.
        return_service : bool
            When True an instance of the Communicator is additionally passed to the callback.
        """
        for rig in self.values():
            rig.assign_callback(event, lambda d: (d, rig) if return_service else callback)

    def clear_callbacks(self, event):
        """
        Clear all callbacks for a given event.

        Parameters
        ----------
        event : str, int, iblutil.io.net.base.ExpMessage
            The event to clear listeners from.

        """
        for rig in self.values():
            rig.clear_callbacks(event)

    async def await_all(self, event):
        """
        Wait for all services to report a given event.

        Parameters
        ----------
        event : str, int, iblutil.io.net.base.ExpMessage
            The event to wait on.

        Returns
        -------
        dict
            A map of rig name and the data that was received.
        """
        async def _return_data(rig):
            return rig.name, await rig.on_event(event)
        event = ExpMessage.validate(event)
        init_futures = set()
        for rig in self.values():
            # init_futures.add(asyncio.create_task(rig.on_event(event)))
            init_futures.add(asyncio.create_task(_return_data(rig)))

        all_initialized = await asyncio.gather(*init_futures)

        # Return map of rig name and data so we know origin of data
        # data_map = {}
        # for data, addr in all_initialized:
        #     host, port = addr
        #     rig = next(x.name for x in self.values() if x.hostname == host and x.port == port)
        #     data_map[rig] = data
        return dict(all_initialized)

    def close(self):
        """Close all communication."""
        for rig in self.values():
            rig.close()


async def main(role, server_uri, name=None, **kwargs):
    """An example of an entry point for creating an individual communicator."""
    if role == 'server':
        print('Starting server')
        com = await EchoProtocol.server(server_uri, name=name, **kwargs)
        try:
            if com.server_uri.startswith('udp'):
                await asyncio.sleep(60 * 60)  # Serve for 1 hour.
            else:
                await com.Server.serve_forever()
        finally:
            com.close()
    elif role == 'client':
        print('Starting client')
        com = await EchoProtocol.client(server_uri, name=name)
        try:
            # Here you would send a message
            await com.start('2022-01-01_1_subject')
        finally:
            com.close()

    else:
        raise ValueError(f'Unknown role "{role}"')


if __name__ == '__main__':
    """
    Examples
    --------
    # Run server
    python udp.py server

    # Run server locally for debugging
    python udp.py server -H localhost

    # Run client for debugging
    python udp.py client
    """
    # Parse parameters
    parser = argparse.ArgumentParser(description='UDP Experiment Communicator.')
    parser.add_argument('role', choices=('server', 'client'),
                        help='communicator role i.e. server or client')
    parser.add_argument('--host', '-H', help='the host address', default=hostname2ip())
    parser.add_argument('--verbose', '-v', action='count', default=0)
    args = parser.parse_args()  # returns data from the options specified

    if args.verbose > 0:
        from iblutil.util import get_logger

        get_logger(_logger.name)
        _logger.setLevel(logging.DEBUG)

    asyncio.run(main(args.role, args.host))
