import sys
import asyncio
import logging
import unittest
from unittest import mock
import ipaddress
import socket
from packaging.version import Version
from datetime import date

from iblutil.io.net import base, app

ver = (getattr(sys.version_info, v) for v in ('major', 'minor', 'micro'))
ver = Version('.'.join(map(str, ver)))


class TestBase(unittest.IsolatedAsyncioTestCase):
    """Test for base network utils.

    NB: This requires internet access.
    """
    def test_parse_uri(self):
        """Tests for parse_uri, validate_ip and hostname2ip"""
        expected = 'udp://192.168.0.1:9999'
        uri = base.validate_uri(expected)
        self.assertEqual(expected, uri)
        self.assertEqual(expected, base.validate_uri(uri[6:]))
        self.assertEqual(expected.replace('udp', 'ws'), base.validate_uri(uri[6:], default_proc='ws'))
        self.assertEqual(expected, base.validate_uri(uri[:-5], default_port=9999))
        uri = base.validate_uri(ipaddress.ip_address('192.168.0.1'), default_port=9999)
        self.assertEqual(expected, uri)
        self.assertEqual('udp://foobar:11001', base.validate_uri('foobar', resolve_host=False))
        # Check IP resolved
        uri = base.validate_uri('http://google.com:80', resolve_host=True)
        expected = (ipaddress.IPv4Address, ipaddress.IPv6Address)
        self.assertIsInstance(ipaddress.ip_address(uri[7:-3]), expected)
        # Check validations
        validations = {'ip': '256.168.0.0000', 'hostname': 'foo@bar$', 'port': 'foobar:00'}
        for subtest, to_validate in validations.items():
            with self.subTest(**{subtest: to_validate}):
                with self.assertRaises(ValueError):
                    base.validate_uri(to_validate, resolve_host=False)
        with self.assertRaises(ValueError):
            base.validate_uri(' ', resolve_host=True)
        with self.assertRaises(TypeError):
            base.validate_uri(b'localhost')

    def test_external_ip(self):
        """Test for external_ip"""
        self.assertFalse(ipaddress.ip_address(base.external_ip()).is_private)

    def test_ExpMessage(self):
        """Test for ExpMessage.validate method."""
        # Check identity
        msg = base.ExpMessage.validate(base.ExpMessage.EXPINFO)
        self.assertIs(msg, base.ExpMessage.EXPINFO)

        # Check integer input
        msg = base.ExpMessage.validate(int(base.ExpMessage.EXPCLEANUP))
        self.assertIs(msg, base.ExpMessage.EXPCLEANUP)

        # Check string input
        msg = base.ExpMessage.validate(' expstatus')
        self.assertIs(msg, base.ExpMessage.EXPSTATUS)

        # Check errors
        with self.assertRaises(TypeError):
            base.ExpMessage.validate(b'EXPSTART')
        with self.assertRaises(ValueError):
            base.ExpMessage.validate('EXPSTOP')

        # Test allow_bitwise kwarg
        event = base.ExpMessage.any()
        self.assertIs(base.ExpMessage.validate(event), event)
        with self.assertRaises(ValueError):
            base.ExpMessage.validate(event, allow_bitwise=False)

    def test_encode(self):
        """Tests for iblutil.io.net.base.Communicator.encode"""
        message = [None, 21, 'message']
        encoded = base.Communicator.encode(message)
        self.assertEqual(encoded, b'[null, 21, "message"]')
        self.assertEqual(base.Communicator.encode(encoded), b'[null, 21, "message"]')

    def test_decode(self):
        """Tests for iblutil.io.net.base.Communicator.decode"""
        data = b'[null, 21, "message"]'
        decoded = base.Communicator.decode(data)
        self.assertEqual(decoded, [None, 21, 'message'])
        with self.assertWarns(Warning):
            decoded = base.Communicator.decode(data + b'"')
            self.assertEqual(decoded, '[null, 21, "message"]"')

    async def test_is_success(self):
        """Tests for iblutil.io.net.base.is_success function."""
        # Expect True only when set_result has been called.
        fut = asyncio.get_event_loop().create_future()
        self.assertFalse(base.is_success(fut))
        fut.set_result(None)
        self.assertTrue(base.is_success(fut))
        fut = asyncio.get_event_loop().create_future()
        fut.cancel()
        self.assertFalse(base.is_success(fut))
        fut = asyncio.get_event_loop().create_future()
        fut.set_exception(RuntimeError)
        self.assertFalse(base.is_success(fut))


@unittest.skipIf(ver < Version('3.9'), 'only version 3.9 or later supported')
class TestUDP(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.server = await app.EchoProtocol.server('localhost', name='server')
        self.client = await app.EchoProtocol.client('localhost', name='client')

    async def test_start(self):
        """Tests confirmed send via start command."""
        # Check socket type
        self.assertIs(self.server._socket.type, app.socket.SOCK_DGRAM)
        self.assertIs(self.client._socket.type, app.socket.SOCK_DGRAM)

        spy = mock.MagicMock()
        self.server.assign_callback('expstart', spy)
        exp_ref = '2022-01-01_1_subject'
        with self.assertLogs(self.server.logger, logging.INFO) as log:
            await self.client.start(exp_ref)
            self.assertIn(f'Received \'[{base.ExpMessage.EXPSTART}, "{exp_ref}", null]', log.records[-1].message)
        spy.assert_called_with([exp_ref, None], (self.client._socket.getsockname()))

    async def test_callback_error(self):
        """Tests behaviour when callback raises exception."""
        callback = mock.MagicMock()
        callback.side_effect = ValueError('Callback failed')

        self.server.assign_callback('expinit', callback)
        task = asyncio.create_task(self.client.on_event(0))
        with self.assertLogs(self.server.logger, logging.ERROR) as log:
            base.Communicator._receive(self.server, b'[1, null]', self.client._socket.getsockname())
            self.assertEqual(1, len(log.records))
            self.assertIn('Callback failed', log.records[-1].message)

        # Check error propagated back to client
        with self.assertLogs(self.client.logger, logging.ERROR) as log:
            (err, evt), _ = await task
            self.assertEqual(1, len(log.records))
            self.assertIn('Callback failed', log.records[-1].message)
        self.assertEqual(base.ExpMessage.EXPINIT.value, evt)
        self.assertIn('Callback failed', err)

        # Check behaviour when future already done
        fut = asyncio.get_running_loop().create_future()
        self.server.assign_callback('EXPSTART', fut)
        fut.set_result(True)
        task = asyncio.create_task(self.client.on_event(2))
        with self.assertLogs(self.server.logger, logging.WARNING) as log:
            base.Communicator._receive(self.server, b'[2, null]', self.client._socket.getsockname())
            self.assertEqual(1, len(log.records))
            self.assertRegex(log.records[-1].getMessage(), 'Future .+ already resolved')

    async def test_on_event(self):
        """Test on_event method as well as init, stop, etc."""
        # INIT
        task = asyncio.create_task(self.server.on_event('expinit'))
        await self.client.init(42)
        actual, _ = await task
        self.assertEqual([42], actual)

        # CLEANUP
        task = asyncio.create_task(self.server.on_event(base.ExpMessage.EXPCLEANUP))
        await self.client.cleanup(8)
        actual, _ = await task
        self.assertEqual([8], actual)

        # STOP
        task = asyncio.create_task(self.server.on_event('EXPEND'))
        await self.client.stop('foo')
        actual, _ = await task
        self.assertEqual(['foo'], actual)

        # INTERRUPT
        task = asyncio.create_task(self.server.on_event('expinterrupt'))
        await self.client.stop('foo', immediately=True)
        actual, _ = await task
        self.assertEqual(['foo'], actual)

        # START
        task = asyncio.create_task(self.server.on_event('expstart'))
        await self.client.start('2020-01-01_1_baz', {'foo': 'bar'})
        actual, _ = await task
        self.assertEqual(['2020-01-01_1_baz', {'foo': 'bar'}], actual)
        task = asyncio.create_task(self.server.on_event('expstart'))
        ref = {'subject': 'baz', 'date': date(2020, 1, 1), 'sequence': 1}
        await self.client.start(ref, {'foo': 'bar'})
        actual, _ = await task
        self.assertEqual(['2020-01-01_1_baz', {'foo': 'bar'}], actual)

        # STATUS
        task = asyncio.create_task(self.server.on_event('EXPSTATUS'))
        await self.client.status(base.ExpStatus.STOPPED)
        actual, _ = await task
        self.assertEqual([base.ExpStatus.STOPPED.value], actual)
        task = asyncio.create_task(self.server.on_event('EXPSTATUS'))
        await self.client.status('CONNECTED')
        actual, _ = await task
        self.assertEqual([base.ExpStatus.CONNECTED.value], actual)

        # INFO
        task = asyncio.create_task(self.server.on_event('expinfo'))
        await self.client.info(base.ExpStatus.RUNNING, {'foo': 'bar'})
        actual, _ = await task
        self.assertEqual([base.ExpStatus.RUNNING.value, {'foo': 'bar'}], actual)

    async def test_alyx(self):
        """Test iblutil.io.net.app.EchoProtocol.alyx method."""
        # Mock an AlyxClient instance that is logged in
        alyx = mock.MagicMock()
        alyx.is_logged_in = True
        alyx.base_url = 'https://alyx.website.net'
        alyx.user = 'foo'
        alyx._token = {'token': '4157aa522b855239cd05f4d23d40563aa0518359'}

        # When Alyx instance is logged in, expect the token to be broadcast
        task = asyncio.create_task(self.server.on_event('ALYX'))
        self.assertIsNone(await self.client.alyx(alyx), 'unexpected argument returned')
        actual, _ = await task  # wait for server process request
        expected = ['https://alyx.website.net', {'foo': {'token': '4157aa522b855239cd05f4d23d40563aa0518359'}}]
        self.assertEqual(expected, actual, 'client failed to send alyx token to server')

        # Client should request and return a token when Alyx instance is not logged in
        async def _req_callback():
            data, addr = await self.server.on_event('ALYX')
            self.assertEqual(['https://alyx.website.net', {}], data)
            await self.server.alyx(alyx, addr)

        # Mock an AlyxClient instance that is not logged in
        alyx_logged_out = mock.MagicMock()
        alyx_logged_out.is_logged_in = False
        alyx_logged_out.base_url = 'https://alyx.website.net'
        alyx_logged_out.user = alyx_logged_out._token = None

        task = asyncio.create_task(_req_callback())
        token = await self.client.alyx(alyx_logged_out)
        await task  # wait for server process request
        self.assertEqual(expected, token, 'failed to return requested token from server')

        # Try the same thing but with None instead of an Alyx instance
        async def _req_callback():
            data, addr = await self.server.on_event('ALYX')
            self.assertEqual([None, {}], data)
            await self.server.alyx(alyx, addr)

        task = asyncio.create_task(_req_callback())
        token = await self.client.alyx(None)
        await task  # wait for server process request
        self.assertEqual(expected, token)

    async def test_confirmed_send_validation(self):
        """Basic tests for iblutil.io.net.app.EchoProtocol.confirmed_send exception handling."""
        # Expect to raise in server role when no address provided
        with self.assertRaises(TypeError):
            await self.server.confirmed_send(None)
        # Expect to raise in client role when provided address does not match server URI
        with self.assertRaises(ValueError):
            await self.client.confirmed_send(None, addr=('localhost', self.client.port + 100))
        # Expect to raise when echo timeout is 0
        try:
            self.client.default_echo_timeout = 0
            with self.assertRaises(ValueError):
                await self.client.confirmed_send(None)
        finally:
            self.client.default_echo_timeout = app.EchoProtocol.default_echo_timeout
        # Expect timeout arg to override default echo timeout, expect error raised on timeout
        assert self.client.is_connected
        with mock.patch('iblutil.io.net.app.asyncio.wait_for', side_effect=asyncio.TimeoutError) as m, \
                self.assertRaises(TimeoutError):
            await self.client.confirmed_send(None, timeout=0.2)
            self.assertFalse(self.client.is_connected, 'failed to close communicator on echo timeout error')
        m.assert_awaited_once_with(mock.ANY, timeout=0.2)
        # Expect to raise RuntimeError with explanation when messages don't match
        with mock.patch('iblutil.io.net.app.asyncio.wait_for', side_effect=RuntimeError), \
                self.assertRaises(RuntimeError) as cm:
            await self.client.confirmed_send(None)
        self.assertIn('unexpected response', str(cm.exception).lower())

    def test_communicator(self):
        """Basic tests for iblutil.io.net.app.EchoProtocol, namely the role setter."""
        # Check role validation
        self.assertEqual(self.server.role, 'server')
        self.assertEqual(self.client.role, 'client')
        with self.assertRaises(ValueError):
            app.EchoProtocol('localhost', 'foo')
        with self.assertRaises(AttributeError):
            self.client.role = 'foo'

    async def test_receive_validation(self):
        """Test for behaviour when non-standard message received."""
        with self.assertWarns(RuntimeWarning), mock.patch.object(self.client, 'send'):
            self.client._receive(b'foo', (self.server.hostname, self.server.port))
        addr = (self.server.hostname, self.server.port)
        fut = asyncio.get_running_loop().create_future()
        self.client._last_sent[addr] = (b'foo', fut)
        with self.assertLogs(self.client.name, logging.ERROR):
            self.client._receive(b'bar', addr)
        self.assertIsInstance(fut.exception(), RuntimeError)
        # Upon receiving message from unknown host, should log warning and return
        with self.assertLogs(self.client.name, logging.WARNING), \
                mock.patch.object(self.client, '_receive') as receive_mock:
            self.client.datagram_received(b'foo', ('192.168.0.0', self.server.port))
            receive_mock.assert_not_called()

    def test_connection_made_validation(self):
        """Test for connection_made method"""
        transport = mock.MagicMock()
        with self.assertRaises(RuntimeError):
            self.client.connection_made(transport)
        transport.get_extra_info().type = socket.SOCK_STREAM
        with self.assertRaises(RuntimeError):
            self.client.connection_made(transport)

    async def test_awaiting_response(self):
        self.assertFalse(self.client.awaiting_response())
        fut = asyncio.get_running_loop().create_future()
        self.client._last_sent[(self.server.hostname, self.server.port)] = (b'foo', fut)
        self.assertTrue(self.client.awaiting_response())
        self.assertFalse(self.client.awaiting_response(addr=('localhost', 8080)))
        fut.cancel()
        self.assertFalse(self.client.awaiting_response())

    async def test_close(self):
        """Test for close/cleanup routine."""
        self.assertTrue(self.client.is_connected)
        loop = asyncio.get_running_loop()
        event_fut = loop.create_future()
        self.client.assign_callback('EXPCLEANUP', event_fut)

        echo_fut = loop.create_future()
        addr = (self.server.hostname, self.server.port)
        self.client._last_sent[addr] = (None, echo_fut)
        self.client.close()

        self.assertFalse(self.client.is_connected)
        self.assertTrue(event_fut.cancelled())
        self.assertTrue(echo_fut.cancelled())
        self.assertFalse(any(self.client._callbacks.values()))
        self.assertTrue(self.client._transport.is_closing())
        self.assertEqual('Close called on communicator', await self.client.on_connection_lost)
        self.assertTrue(self.client.on_eof_received.cancelled())
        self.assertTrue(self.client.on_error_received.cancelled())
        # self.assertEqual(-1, self.client._socket.fileno())  # Closed later on in loop

    async def test_on_error_received(self):
        """Test for on_error_received callback."""
        ex = ValueError('foo')
        with self.assertLogs(self.client.name, logging.ERROR):
            self.client.error_received(ex)
        self.assertTrue(self.client.on_error_received.done())
        self.assertEqual(ex, self.client.on_error_received.result())

    def tearDown(self):
        self.client.close()
        self.server.close()


class TestWebSockets(unittest.IsolatedAsyncioTestCase):
    """Test net.app.EchoProtocol with a TCP/IP transport layer"""
    port = 18888

    async def asyncSetUp(self):
        self.server = await app.EchoProtocol.server(f'ws://localhost:{self.port}', name='server')
        self.client = await app.EchoProtocol.client(f'ws://localhost:{self.port}', name='client')
        TestWebSockets.port += 1

    async def test_start(self):
        """Tests confirmed send via start command."""
        # Check socket indeed TCP
        self.assertIs(self.server._socket.type, app.socket.SOCK_STREAM)
        self.assertIs(self.client._socket.type, app.socket.SOCK_STREAM)

        spy = mock.MagicMock()
        self.server.assign_callback('expstart', spy)

        exp_ref = '2022-01-01_1_subject'
        with self.assertLogs(self.server.logger, logging.INFO) as log:
            await self.client.start(exp_ref)
            self.assertIn(f'Received \'[{base.ExpMessage.EXPSTART}, "{exp_ref}", null]', log.records[-1].message)
        spy.assert_called_with([exp_ref, None], (self.client._socket.getsockname()))

    def test_send_validation(self):
        """Test for Communicator.send method."""
        message = b'foo'
        with mock.patch.object(self.client, '_transport') as transport:
            self.client.send(message)
            transport.write.assert_called_with(message)
            transport.write.reset_mock()
            # Check returns when external address used
            with self.assertLogs(self.client.name, logging.WARNING):
                self.client.send(message, addr=('192.168.0.0', 0))
            transport.write.assert_not_called()

    def test_connection_made_validation(self):
        """Test for connection_made method"""
        transport = mock.MagicMock()
        transport.get_extra_info().type = socket.SOCK_DGRAM
        with self.assertRaises(RuntimeError):
            self.client.connection_made(transport)

    def tearDown(self):
        self.client.close()
        self.server.close()


@unittest.skipIf(ver < Version('3.9'), 'only version 3.9 or later supported')
class TestServices(unittest.IsolatedAsyncioTestCase):
    """Tests for the app.Services class"""

    async def asyncSetUp(self):
        # On each acquisition PC
        self.server_1 = await app.EchoProtocol.server('localhost', name='server')
        # On main experiment PC
        self.client_1 = await app.EchoProtocol.client('localhost', name='client1')
        self.client_2 = await app.EchoProtocol.client('localhost', name='client2')
        # For some tests we'll need multiple servers (avoids having to run on multiple threads)
        self.server_2 = await app.EchoProtocol.server('localhost:10002', name='server2')
        self.client_3 = await app.EchoProtocol.client('localhost:10002', name='client3')

    async def test_type(self):
        """Test that services are immutable"""
        services = app.Services([self.client_1, self.client_2])
        # Ensure our services stack is immutable
        with self.assertRaises(TypeError):
            services['client2'] = app.EchoProtocol
        with self.assertRaises(TypeError):
            services.pop('client1')
        # Ensure inputs are validated
        with self.assertRaises(TypeError):
            app.Services([self.client_1, None])

    async def test_close(self):
        """Test Services.close method"""
        clients = [self.client_1, self.client_2]
        assert all(x.is_connected for x in clients)
        services = app.Services(clients)
        self.assertTrue(services.is_connected)
        services.close()
        self.assertFalse(services.is_connected)
        self.assertTrue(not any(x.is_connected for x in clients))

    async def test_assign(self):
        """Tests for Services.assign_callback and Services.clear_callbacks"""
        # Assign a callback for an event
        callback = mock.MagicMock(spec_set=True)
        clients = (self.client_1, self.client_2)
        services = app.Services(clients)
        services.assign_callback('EXPINIT', callback)

        for addr in map(lambda x: x._socket.getsockname(), clients):
            await self.server_1.init('foo', addr=addr)

        self.assertEqual(2, callback.call_count)
        callback.assert_called_with(['foo'], ('127.0.0.1', 11001))

        # Check return_service arg
        callback2 = mock.MagicMock(spec_set=True)
        services.assign_callback('EXPINIT', callback2, return_service=True)
        for addr in map(lambda x: x._socket.getsockname(), clients):
            await self.server_1.init('foo', addr=addr)
        self.assertEqual(2, callback2.call_count)
        callback2.assert_called_with(['foo'], ('127.0.0.1', 11001), self.client_2)

        # Check validation
        with self.assertRaises(TypeError):
            services.assign_callback('EXPEND', 'foo')

        # Check clear callbacks
        services.assign_callback('EXPINIT', callback2)
        removed = services.clear_callbacks('EXPINIT', callback)
        self.assertEqual({'client1': 1, 'client2': 1}, removed)
        removed = services.clear_callbacks('EXPINIT')
        self.assertEqual({'client1': 2, 'client2': 2}, removed)
        # Check futures cancelled
        fut = asyncio.get_running_loop().create_future()
        services.assign_callback('EXPINIT', fut)
        assert not fut.cancelled()
        services.clear_callbacks('EXPINIT')
        self.assertTrue(fut.cancelled())

    async def test_init(self):
        """Test init of services.

        Unfortunately this test is convoluted due to the client and server being on the same
        machine.
        """
        clients = (self.client_1, self.client_3)
        # Require two servers as we'll need two callbacks
        servers = (self.server_1, self.server_2)

        # Set up the client response callbacks that the server (Services object) will await.

        async def respond(server, fut):
            """Response callback for the server"""
            data, addr = await fut
            await asyncio.sleep(.1)  # FIXME Should be able to somehow use loop.call_soon
            await server.init(42, addr)

        for server in servers:
            asyncio.create_task(respond(server, server.on_event(base.ExpMessage.EXPINIT)))

        # Create the services and initialize them, awaiting the callbacks we just set up
        services = app.Services(clients)
        responses = await services.init('foo')

        # Test outcomes
        self.assertFalse(any(map(asyncio.isfuture, responses.values())))
        for name, value in responses.items():
            with self.subTest(client=name):
                self.assertEqual([42], value)

        # Add back the callbacks to test sequential init
        for server in servers:
            asyncio.create_task(respond(server, server.on_event(base.ExpMessage.EXPINIT)))

        # Initialize services sequentially, awaiting the callbacks we just set up
        responses = await services.init('foo', concurrent=False)

        # Test outcomes
        self.assertFalse(any(map(asyncio.isfuture, responses.values())))
        for name, value in responses.items():
            with self.subTest(client=name):
                self.assertEqual([42], value)

    async def test_service_methods(self):
        """Test start, stop, etc. methods.

        For a more complete test, see test_init.
        """
        clients = [mock.AsyncMock(spec=app.EchoProtocol), mock.AsyncMock(spec=app.EchoProtocol)]
        services = app.Services(clients)

        # Init
        await services.init([42, 'foo'])
        for client in clients:
            client.init.assert_awaited_once_with(data=[42, 'foo'])

        # Start
        ref = '2020-01-01_1_subject'
        await services.start(ref)
        for client in clients:
            client.start.assert_awaited_once_with(ref, data=None)

        # Info
        await services.info(base.ExpStatus.RUNNING, {'exp_ref': ref})
        for client in clients:
            client.info.assert_awaited_once_with(base.ExpStatus.RUNNING, data={'exp_ref': ref})

        # Status
        await services.status(base.ExpStatus.STOPPED)
        for client in clients:
            client.status.assert_awaited_once_with(base.ExpStatus.STOPPED)

        # Stop
        await services.stop(immediately=True)
        for client in clients:
            client.stop.assert_awaited_once_with(data=None, immediately=True)

        # Cleanup
        await services.cleanup(data=[42, 'foo'])
        for client in clients:
            client.cleanup.assert_awaited_once_with(data=[42, 'foo'])

        # Alyx
        alyx = mock.MagicMock()
        await services.alyx(alyx)
        for client in clients:
            client.alyx.assert_awaited_once_with(alyx)

    async def test_sequential_signal(self):
        """Test for Services._signal method with concurrent=False"""
        clients = [mock.AsyncMock(spec=app.EchoProtocol), mock.AsyncMock(spec=app.EchoProtocol)]
        for i, client in enumerate(clients):
            client.name = f'client_{i}'
            client.on_event.return_value = ([i], (self.client_1.hostname, self.client_1.port))
        services = app.Services(clients)
        responses = await services._signal(base.ExpMessage.EXPINIT, 'init', 'foo', concurrent=False)
        for client in clients:
            client.init.assert_awaited_once()
        self.assertEqual(responses, {'client_0': [0], 'client_1': [1]})

    def tearDown(self):
        self.client_1.close()
        self.client_2.close()
        self.server_1.close()
        self.server_2.close()
        self.client_3.close()


if __name__ == '__main__':
    from iblutil.util import setup_logger
    setup_logger(app.__name__, level=logging.DEBUG)

    unittest.main()
