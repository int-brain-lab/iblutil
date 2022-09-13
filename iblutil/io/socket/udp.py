import json
import urllib.parse
import urllib.request
import logging
import asyncio
import argparse

from iblutil.io.socket.base import Communicator, LISTEN_PORT, validate_uri, hostname2ip
_logger = logging.getLogger(__name__)


def _address2tuple(address):
    server_uri = validate_uri(address, default_port=LISTEN_PORT)
    parsed_uri = urllib.parse.urlparse(server_uri)
    return parsed_uri.hostname, parsed_uri.port


class UDPEchoProtocol(Communicator, asyncio.DatagramProtocol):
    """A UDP server implementing DatagramTransport"""
    def __init__(self):
        self._transport = None
        self._socket = None
        self._role = None
        # For validating echo'd response
        self._last_sent = None
        self._echo_future = None

    @property
    def is_open(self):
        return self._transport and not self._transport.is_closing()

    def receive(self):
        pass

    async def cleanup(self):
        pass

    async def start(self, exp_ref):
        await self.confirmed_send(('EXPSTART', exp_ref))

    async def stop(self):
        pass

    def bind(self):
        _logger.debug('Connected')
        pass

    @staticmethod
    def encode(data):
        """Serialize data for transmission"""
        if isinstance(data, bytes):
            return data
        if not isinstance(data, str):
            data = json.dumps(data)
        return data.encode()

    def send(self, data):
        """Send data to clients.

        Serialize data and pass to transport layer.
        """
        _logger.debug(f'Send "{data}" to {self.server_uri}')
        self._transport.sendto(self.encode(data))

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
        self.bind()

    def datagram_received(self, data, addr):
        msg = data.decode()
        host, port = addr[:2]
        if host != self.hostname:
            _logger.warning(f'Ignoring UDP packet from unexpected host ({host}:{port}) with message "{msg}"', )
            return
        _logger.info('Received %r from udp://%s:%i', msg, host, port)
        if self._role == 'server':  # echo
            _logger.debug('Send %r to udp://%s:%i', msg, host, port)
            self._transport.sendto(data, addr)
        elif self._role == 'client' and self._last_sent and self._echo_future:
            if data != self._last_sent:
                self._echo_future.set_exception(RuntimeError)
            else:
                self._echo_future.set_result(True)

    def error_received(self, exc):
        print('Error received:', exc)

    def connection_lost(self, exc):
        _logger.info('Connection closed')
        if getattr(self, 'on_con_lost', False):  # TODO Set up event mode callbacks
            self.on_con_lost.set_result(True)

    # Factory methods for instantiating a server or client

    @staticmethod
    async def server(server_uri, **kwargs) -> 'UDPEchoProtocol':
        """Create a server instance"""
        # Validate server URI
        server_uri = validate_uri(server_uri)

        # Get a reference to the event loop
        loop = asyncio.get_running_loop()

        # One protocol instance will be created to serve all client requests.
        _, protocol = await loop.create_datagram_endpoint(
            UDPEchoProtocol,
            local_addr=_address2tuple(server_uri), **kwargs)
        protocol._role = 'server'
        protocol.server_uri = server_uri
        _logger.info(f'Listening on {protocol.server_uri}')
        return protocol

    @staticmethod
    async def client(server_uri) -> 'UDPEchoProtocol':
        # Validate server URI
        server_uri = validate_uri(server_uri)

        # Get a reference to the event loop
        loop = asyncio.get_running_loop()

        transport, protocol = await loop.create_datagram_endpoint(
            UDPEchoProtocol, remote_addr=_address2tuple(server_uri))

        protocol._role = 'client'
        protocol.server_uri = server_uri
        return protocol


async def main(role, server_uri, **kwargs):
    if role == 'server':
        print('Starting UDP server')
        com = await UDPEchoProtocol.server(server_uri, **kwargs)
        try:
            await asyncio.sleep(60 * 60)  # Serve for 1 hour.
        finally:
            com.close()
    elif role == 'client':
        print('Starting UDP client')
        # on_con_lost = (asyncio.get_running_loop()).create_future()
        com = await UDPEchoProtocol.client(server_uri)
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
