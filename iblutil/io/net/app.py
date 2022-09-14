import json
import urllib.parse
import urllib.request
import logging
import asyncio
import argparse
import socket
from functools import partial

from iblutil.io.net.base import Communicator, LISTEN_PORT, validate_uri, hostname2ip
_logger = logging.getLogger(__name__)


def _address2tuple(address):
    server_uri = validate_uri(address, default_port=LISTEN_PORT)
    parsed_uri = urllib.parse.urlparse(server_uri)
    return parsed_uri.hostname, parsed_uri.port


class EchoProtocol(Communicator):
    """An echo server implementing TCP/IP and UDP"""
    Server = None
    _role = None

    def __init__(self, server_uri, role):
        self._transport = None
        self._socket = None
        self.role = role
        self.server_uri = server_uri
        # For validating echo'd response
        self._last_sent = None
        self._echo_future = None

    @property
    def role(self):
        return self._role

    @role.setter
    def role(self, value):
        if self._role is not None:
            raise AttributeError('can\'t set attribute')
        if value.strip().lower() not in ('server', 'client'):
            raise ValueError(f'role must be either "server" or "client"')
        self._role = value.strip().lower()

    @property
    def is_connected(self):
        return self._transport and not self._transport.is_closing()

    @property
    def awaiting_response(self):
        return self._last_sent and self._echo_future

    def receive(self, data, addr):
        if isinstance(data, list):
            event, data = data
            for fcn in self._callbacks[event.upper()]:
                fcn(data, addr)

    async def cleanup(self):
        pass

    async def start(self, exp_ref):
        await self.confirmed_send(('EXPSTART', exp_ref))

    async def stop(self):
        await self.confirmed_send(('EXPEND', None))

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
            self._transport.sendto(data, addr)
        else:
            self._transport.write(self.encode(data))

    async def confirmed_send(self, data, timeout=10):
        assert self._role == 'client'
        self._last_sent = self.encode(data)
        self.send(self._last_sent)
        # Sockets can no longer be blocking, so we'll wait ourselves.
        try:
            loop = asyncio.get_running_loop()
            self._echo_future = loop.create_future()
            await asyncio.wait_for(self._echo_future, timeout=timeout)
        except asyncio.TimeoutError:
            self.close()
            raise TimeoutError('Failed to receive server response in time')
        except RuntimeError:
            self.close()
            raise RuntimeError('Unexpected response from server')
        self._echo_future = None
        _logger.debug('Confirmation received')

    def close(self):
        if self._transport:
            self._transport.close()
        if self._echo_future:
            self._echo_future.cancel()

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

    def datagram_received(self, data, addr):
        """Called by UDP transport layer"""
        host, port = addr[:2]
        if host != self.hostname:
            _logger.warning(f'Ignoring UDP packet from unexpected host ({host}:{port}) with message "{data}"')
        else:
            msg = data.decode()
            _logger.info('Received %r from %s://%s:%i', msg, self.protocol, host, port)
            if self._role == 'server':  # echo
                _logger.debug('Send %r to %s://%s:%i', msg, self.protocol, host, port)
                self.send(data, addr)
            elif self._role == 'client' and self.awaiting_response:
                if data != self._last_sent:
                    self._echo_future.set_exception(RuntimeError)
                else:
                    self._echo_future.set_result(True)
                    return
            self.receive(self.decode(data), addr)

    def data_received(self, data):
        """Called by TCP/IP transport layer"""
        msg = data.decode()
        addr = self._transport.get_extra_info('peername')[:2]
        host, port = addr
        _logger.info('Received %r from %s://%s:%i', msg, self.protocol, host, port)
        if self._role == 'server':  # echo
            _logger.debug('Send %r to %s://%s:%i', msg, self.protocol, host, port)
            self._transport.write(data)
        elif self._role == 'client' and self.awaiting_response:
            if data != self._last_sent:
                self._echo_future.set_exception(RuntimeError)
            else:
                self._echo_future.set_result(True)
            return
        self.receive(self.decode(data), addr)

    def error_received(self, exc):
        print('Error received:', exc)

    def eof_received(self,):
        _logger.debug('EOF received')

    def connection_lost(self, exc):
        _logger.info('Connection closed')
        if getattr(self, 'on_con_lost', False):  # TODO Set up event mode callbacks
            self.on_con_lost.set_result(True)

    # Factory methods for instantiating a server or client

    @staticmethod
    async def server(server_uri, **kwargs) -> 'EchoProtocol':
        """Create a server instance"""
        # Validate server URI
        server_uri = validate_uri(server_uri)

        # Get a reference to the event loop
        loop = asyncio.get_running_loop()

        # One protocol instance will be created to serve all client requests.
        if server_uri.startswith('udp'):
            Protocol = partial(EchoProtocol, server_uri, 'server')
            _, protocol = await loop.create_datagram_endpoint(Protocol, local_addr=_address2tuple(server_uri), **kwargs)
        else:
            protocol = EchoProtocol(server_uri, 'server')
            protocol.Server = await loop.create_server(lambda: protocol, *_address2tuple(server_uri), **kwargs)

        _logger.info(f'Listening on {protocol.server_uri}')
        return protocol

    @staticmethod
    async def client(server_uri, **kwargs) -> 'EchoProtocol':
        # Validate server URI
        server_uri = validate_uri(server_uri)

        # Get a reference to the event loop
        loop = asyncio.get_running_loop()

        Protocol = partial(EchoProtocol, server_uri, 'client')
        if server_uri.startswith('udp'):
            _, protocol = await loop.create_datagram_endpoint(Protocol, remote_addr=_address2tuple(server_uri), **kwargs)
        else:
            _, protocol = await loop.create_connection(Protocol, *_address2tuple(server_uri), **kwargs)

        return protocol


async def main(role, server_uri, **kwargs):
    if role == 'server':
        print('Starting server')
        com = await EchoProtocol.server(server_uri, **kwargs)
        try:
            if com.server_uri.startswith('udp'):
                await asyncio.sleep(60 * 60)  # Serve for 1 hour.
            else:
                await com.Server.serve_forever()
        finally:
            com.close()
    elif role == 'client':
        print('Starting client')
        # on_con_lost = (asyncio.get_running_loop()).create_future()
        com = await EchoProtocol.client(server_uri)
        try:
            # Here you would send a message
            await com.start('2022-01-01_1_subject')
            # await on_con_lost
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
