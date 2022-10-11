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

from iblutil.io.net import base

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
    server_uri = base.validate_uri(address, default_port=base.LISTEN_PORT)
    parsed_uri = urllib.parse.urlparse(server_uri)
    return parsed_uri.hostname, parsed_uri.port


class EchoProtocol(base.Communicator):
    """An echo server implementing TCP/IP and UDP.

    This should be instantiated using either EchoProtocol.server or EchoProtocol.client.
    In the client role, the remote address is specified; in the server role, the local address is
    specified.

    Attributes
    ----------
    Server : asyncio.Server
        A network server instance if using TCP/IP.
    role : {'client', 'server'}
        The communicator role.  A server may communicate with multiple clients. The server URI
        specifies its local address.  A client only communicates with a single host, specified by
        the server URI.
    default_echo_timeout : float
        The default maximum time in seconds to await a message echo.
    _last_sent : dict[(str, int), (bytes, asyncio.Future)]
        A map of addresses holding the last sent bytes str and the future being waited on.  In
        client mode there should only be one entry - the server URI.
    """

    Server = None
    _role = None
    default_echo_timeout = 1.

    def __init__(self, server_uri, role, name=None):
        super().__init__(server_uri, name=name)
        self._transport = None
        self._socket = None
        self.role = role
        # For validating echo'd response
        self._last_sent = {}
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
    def awaiting_response(self, addr=None) -> bool:
        """bool: True if awaiting confirmation of receipt from remote."""
        if addr:
            last_sent = self._last_sent.get(addr, False)
            return last_sent and not last_sent[1].done()
        else:
            return self._last_sent and any(not x[1].done() for x in self._last_sent.values())

    async def cleanup(self, data=None):
        """Cleanup experiment.

        Send a cleanup message to the remote host.

        Parameters
        ----------
        data : any
            Optional extra data to send to the remote host.

        Raises
        ------
        TimeoutError
            Remote host failed to echo the message within the timeout period.
        """
        message = super().cleanup(data)
        await self.confirmed_send(message)

    async def start(self, exp_ref, data=None):
        """Start an experiment.

        Send a stop message to the remote host.

        Parameters
        ----------
        exp_ref : str
            A experiment reference string in the form yyyy-mm-dd_n_subject.
        data : any
            Optional extra data to send to the remote host.

        Raises
        ------
        TimeoutError
            Remote host failed to echo the message within the timeout period.
        """
        message = super().start(exp_ref, data)
        await self.confirmed_send(message)

    async def stop(self, data=None, immediately=False):
        """End an experiment.

        Send a stop message to the remote host.

        Parameters
        ----------
        data : any
            Optional extra data to send to the remote host.
        immediately : bool
            If True, an EXPINTERRUPT signal is used.

        Raises
        ------
        TimeoutError
            Remote host failed to echo the message within the timeout period.
        """
        message = super().stop(data)
        await self.confirmed_send(message)

    async def init(self, data=None, addr=None):
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
        await self.confirmed_send(message, addr=addr)

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
        _logger.debug(f'[{self.name}] Send "{data}" to {self.server_uri}')
        if self.protocol == 'udp':
            self._transport.sendto(data, addr or (self.hostname, self.port))
        else:
            assert not addr
            self._transport.write(self.encode(data))

    async def confirmed_send(self, data, addr=None, timeout=None):
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
            Unexpected remote address: in client mode the address must match server_uri.
        TypeError
            In server mode a remote address must be provided.
        """
        if self.role == 'server':
            if not addr:
                raise TypeError('confirmed_send missing 1 required argument: \'addr\'')
        elif addr and addr != (self.hostname, self.port):
            raise ValueError('Unexpected remote address')
        addr = addr or (self.hostname, self.port)
        if not (timeout := timeout or self.default_echo_timeout) > 0:
            raise ValueError('Timeout must be non-zero number')
        loop = asyncio.get_running_loop()
        echo_future = loop.create_future()
        self._last_sent[addr] = (self.encode(data), echo_future)
        self.send(self._last_sent[addr][0], addr=addr)
        # Sockets can no longer be blocking, so we'll wait ourselves.
        try:
            await asyncio.wait_for(echo_future, timeout=timeout)
        except asyncio.TimeoutError:
            self.close()
            raise TimeoutError('Failed to receive client response in time')
        except RuntimeError:
            self.close()
            raise RuntimeError('Unexpected response from server')
        self._last_sent.pop(addr)
        _logger.debug(f'[{self.name}] Confirmation received')

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
        echo_futures = map(lambda x: x[1], self._last_sent.values())
        for fut in filter(lambda f: not f.done(), echo_futures):
            fut.cancel('Close called on communicator')
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
        _logger.debug(f'[{self.name}] Connected with socket {self._socket}')

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
        - Callbacks apply only to new messages, not echo responses.  EchoProtocol.confirmed_send
        should be awaited, however it is possible to assign a callback for receipt of an echo with
        EchoProtocol._last_sent[addr][1].add_done_callback.
        - Currently this only checks the received message, not its origin.
        """
        host, port = addr[:2]
        msg = data.decode()
        _logger.info('[%s] Received %r from %s://%s:%i', self.name, msg, self.protocol, host, port)
        if last_sent := self._last_sent.get(addr):
            expected, echo_future = last_sent
            # If echo doesn't match, raise exception
            if data != expected:
                _logger.error('[%s] Expected %s from %s, got %s',
                              self.name, expected, self.name, data)
                echo_future.set_exception(RuntimeError)
            else:  # Notify callbacks of receipt
                echo_future.set_result(True)
        else:
            # Update from remote
            _logger.debug('[%s] Send %r to %s://%s:%i', self.name, msg, self.protocol, host, port)
            self.send(data, addr)  # Echo
            super()._receive(data, addr)  # Process callbacks

    def datagram_received(self, data, addr):
        """Called by UDP transport layer"""
        host, port = addr[:2]
        if host != self.hostname:
            _logger.warning(
                f'[{self.name}] Ignoring UDP packet from unexpected host '
                '({host}:{port}) with message "{data}"')
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
        server_uri : str, ipaddress.IPv4Address, ipaddress.IPv6Address
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
        server_uri = base.validate_uri(server_uri)

        # Get a reference to the event loop
        loop = asyncio.get_running_loop()

        # One protocol instance will be created to serve all client requests.
        if server_uri.startswith('udp'):
            Protocol = partial(EchoProtocol, server_uri, 'server', name=name)
            _, protocol = await loop.create_datagram_endpoint(Protocol, local_addr=_address2tuple(server_uri), **kwargs)
        else:
            protocol = EchoProtocol(server_uri, 'server', name=name)
            protocol.Server = await loop.create_server(lambda: protocol, *_address2tuple(server_uri), **kwargs)

        _logger.info(f'[{name}] Listening on {protocol.server_uri}')
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
        server_uri = base.validate_uri(server_uri)

        # Get a reference to the event loop
        loop = asyncio.get_running_loop()

        Protocol = partial(EchoProtocol, server_uri, 'client', name=name)
        if server_uri.startswith('udp'):
            _, protocol = await loop.create_datagram_endpoint(Protocol, remote_addr=_address2tuple(server_uri), **kwargs)
        else:
            _, protocol = await loop.create_connection(Protocol, *_address2tuple(server_uri), **kwargs)

        return protocol


class Services(base.Service, UserDict):
    """Handler for multiple remote rig services."""
    __slots__ = ('timeout', 'server')

    def __init__(self, remote_rigs, alyx=None, timeout=10.):
        """Handler for multiple remote rig services.

        Parameters
        ----------
        remote_rigs : list(iblutil.io.net.base.Service)
            A list of remote rig service objects.
        alyx : one.webclient.AlyxClient
            An optional Alyx instance to send on request.
        timeout : float
            How long to wait for response from client(s).
        """
        # Store rig communicators by name
        super().__init__()
        if not all(isinstance(x, base.Service) for x in remote_rigs):
            raise TypeError(f'Remote services must be of type {type(base.Service)}')
        self.data = MappingProxyType({rig.name: rig for rig in remote_rigs})  # Ensure immutable
        self.timeout = timeout

        # Register callbacks so that if an Alyx instance is requested the provided token is sent.
        if alyx:
            for rig in self.values():
                # FIXME This won't work; unawaited call
                rig.assign_callback(base.ExpMessage.ALYX, lambda _: rig.alyx(alyx))

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
        if return_service:
            callback = lambda d: callback(d, rig)
        for rig in self.values():
            rig.assign_callback(event, callback)

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
        responses = {}

        async def _return_data(rig, response) -> None:
            """Return map of rig name and data so we know origin of data"""
            data, _ = await response
            responses[rig.name] = data
            return response

        event = base.ExpMessage.validate(event)
        tasks = set()
        for rig in self.values():
            task = asyncio.create_task(_return_data(rig, rig.on_event(event)))
            tasks.add(task)

        if self.timeout:
            _, pending = await asyncio.wait(
                tasks, timeout=self.timeout, return_when=asyncio.ALL_COMPLETED
            )
            if any(pending):
                failed = set(self.keys()).difference(responses.keys())
                raise asyncio.TimeoutError(
                    f'The following services failed to respond in time: {failed}')
        else:
            await asyncio.gather(*tasks)

        return responses

    def close(self):
        """Close all communication."""
        for rig in self.values():
            rig.close()

    async def init(self, data=None, concurrent=True):
        """Initialize an experiment.

        Send an initialization signal to the remote services and await the responses.

        Parameters
        ----------
        data : any
            Optional extra data to send to the remote host.
        concurrent : bool
            If false, wait for response from each service before communicating with the next.

        Returns
        -------
        dict of str
            A dictionary of service names and the response data received.

        Raises
        ------
        TimeoutError
            Remote host failed to echo the message within the timeout period.
            Remote host failed to respond within response period.
        """
        event = base.ExpMessage['EXPINIT']
        return await self._signal(event, 'init', data=data, concurrent=concurrent)

    async def cleanup(self, data=None, concurrent=True):
        """Cleanup an experiment.

        Send an cleanup signal to the remote services and await responses.

        Parameters
        ----------
        data : any
            Optional extra data to send to the remote host.
        concurrent : bool
            If false, wait for response from each service before communicating with the next.

        Returns
        -------
        dict of str
            A dictionary of service names and the response data received.

        Raises
        ------
        TimeoutError
            Remote host failed to echo the message within the timeout period.
            Remote host failed to respond within response period.
        """
        event = base.ExpMessage.EXPCLEANUP
        return await self._signal(event, 'cleanup', data=data, concurrent=concurrent)

    async def start(self, exp_ref, data=None, concurrent=True):
        """Start an experiment.

        Send a start signal to the remote services and await responses.

        Parameters
        ----------
        exp_ref : str
            An experiment reference string in the form yyyy-mm-dd_n_subject.
        data : any
            Optional extra data to send to the remote host.
        concurrent : bool
            If false, wait for response from each service before communicating with the next.

        Returns
        -------
        dict of str
            A dictionary of service names and the response data received.

        Raises
        ------
        TimeoutError
            Remote host failed to echo the message within the timeout period.
            Remote host failed to respond within response period.
        """
        event = base.ExpMessage.EXPSTART
        return await self._signal(event, 'start', exp_ref, data=data, concurrent=concurrent)

    async def stop(self, data=None, immediately=False, **kwargs):
        """End an experiment.

        Send a stop signal to the remote services and await responses.

        Parameters
        ----------
        data : any
            Optional extra data to send to the remote host.
        immediately : bool
            If true, send an EXPINTERRUPT signal.
        concurrent : bool
            If false, wait for response from each service before communicating with the next.

        Returns
        -------
        dict of str
            A dictionary of service names and the response data received.

        Raises
        ------
        TimeoutError
            Remote host failed to echo the message within the timeout period.
            Remote host failed to respond within response period.
        """
        event = base.ExpMessage.EXPEND
        return await self._signal(event, 'stop', data=data, immediately=immediately, **kwargs)

    async def _signal(self, event, method, *args, concurrent=True, **kwargs):
        """Send an event signal to the remote services and await responses.

        Parameters
        ----------
        event : iblutil.io.net.base.ExpMessage
            The event to signal to services.
        method : str
            The name of the method to call for each service.
        *args
            Positional arguments to pass to method.
        concurrent : bool
            If true, all services are signaled concurrently.
        **kwargs
            Keyword arguments to pass to method.

        Returns
        -------
        dict of str
            A dictionary of service names and the response data received.
        """
        if concurrent:
            for service in self.values():
                f = getattr(service, method or event.name.lower())
                await f(*args, **kwargs)
            responses = await self.await_all(event)
        else:
            responses = dict.fromkeys(self.keys())
            for name, service in self.items():
                f = getattr(service, method or event.name.lower())
                await f(*args, **kwargs)
                if self.timeout:
                    data, _ = await asyncio.wait_for(service.on_event(event), self.timeout)
                else:
                    data, _ = await service.on_event(event)
                responses[service.name] = data
        return responses

    async def alyx(self, alyx):
        """
        Send Alyx token to remote services.

        Parameters
        ----------
        alyx : one.webclient.AlyxClient
            An instance of Alyx to extract and send token from.
        """
        for service in self.values():
            await service.alyx(alyx)


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
    parser.add_argument('--host', '-H', help='the host address', default=base.hostname2ip())
    parser.add_argument('--verbose', '-v', action='count', default=0)
    args = parser.parse_args()  # returns data from the options specified

    if args.verbose > 0:
        from iblutil.util import get_logger

        get_logger(_logger.name)
        _logger.setLevel(logging.DEBUG)

    asyncio.run(main(args.role, args.host))
