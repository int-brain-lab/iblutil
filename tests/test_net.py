import asyncio
import logging
import unittest
from unittest import mock
import ipaddress
import socket

from iblutil.io.net import base, app

import sys
ver = float('%i.%i' % sys.version_info[:2])


class TestBase(unittest.TestCase):
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
        self.assertEqual('udp://foobar:10001', base.validate_uri('foobar', resolve_host=False))
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
        """Test for ExpMessage.validate method"""
        # Check identity
        msg = base.ExpMessage.validate(base.ExpMessage.EXPINFO)
        self.assertIs(msg, base.ExpMessage.EXPINFO)

        # Check integer input
        msg = base.ExpMessage.validate(40)
        self.assertIs(msg, base.ExpMessage.EXPCLEANUP)

        # Check string input
        msg = base.ExpMessage.validate(' expstatus')
        self.assertIs(msg, base.ExpMessage.EXPSTATUS)

        # Check errors
        with self.assertRaises(TypeError):
            base.ExpMessage.validate(b'EXPSTART')
        with self.assertRaises(ValueError):
            base.ExpMessage.validate('EXPSTOP')

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


@unittest.skipIf(ver < 3.9, 'only version 3.9 or later supported')
class TestUDP(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.server = await app.EchoProtocol.server('localhost', name='server')
        self.client = await app.EchoProtocol.client('localhost', name='client')

    async def test_start(self):
        """Tests confirmed send via start command"""
        # Check socket type
        self.assertIs(self.server._socket.type, app.socket.SOCK_DGRAM)
        self.assertIs(self.client._socket.type, app.socket.SOCK_DGRAM)

        spy = mock.MagicMock()
        self.server.assign_callback('expstart', spy)
        exp_ref = '2022-01-01_1_subject'
        with self.assertLogs(self.server.logger, logging.INFO) as log:
            await self.client.start(exp_ref)
            self.assertIn(f'Received \'[20, "{exp_ref}", null]', log.records[-1].message)
        spy.assert_called_with([exp_ref, None], (self.client._socket.getsockname()))

    async def test_callback_error(self):
        """Tests behaviour when callback raises exception"""
        callback = mock.MagicMock()
        callback.side_effect = ValueError('Callback failed')

        self.server.assign_callback('expinit', callback)
        task = asyncio.create_task(self.server.on_event('expinterrupt'))
        with self.assertLogs(self.server.logger, logging.ERROR) as log:
            base.Communicator._receive(self.server, b'[10, null]', self.client._socket.getsockname())
            self.assertEqual(1, len(log.records))
            self.assertIn('Callback failed', log.records[-1].message)

        # Check error propagated back to client
        (err,), _ = await task
        self.assertIn('Callback failed', err)

    async def test_on_event(self):
        """Test on_event method as well as init, stop and cleanup"""
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

    def test_communicator(self):
        """Basic tests for iblutil.io.net.app.EchoProtocol"""
        # Check role validation
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

    def tearDown(self):
        self.client.close()
        self.server.close()


@unittest.skipIf(ver < 3.9, 'only version 3.9 or later supported')
class TestWebSockets(unittest.IsolatedAsyncioTestCase):
    """Test net.app.EchoProtocol with a TCP/IP transport layer"""

    async def asyncSetUp(self):
        self.server = await app.EchoProtocol.server('ws://localhost:8888', name='server')
        self.client = await app.EchoProtocol.client('ws://localhost:8888', name='client')

    async def test_start(self):
        """Tests confirmed send via start command"""
        # Check socket indeed TCP
        self.assertIs(self.server._socket.type, app.socket.SOCK_STREAM)
        self.assertIs(self.client._socket.type, app.socket.SOCK_STREAM)

        spy = mock.MagicMock()
        self.server.assign_callback('expstart', spy)

        exp_ref = '2022-01-01_1_subject'
        with self.assertLogs(self.server.logger, logging.INFO) as log:
            await self.client.start(exp_ref)
            self.assertIn(f'Received \'[20, "{exp_ref}", null]', log.records[-1].message)
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


@unittest.skipIf(ver < 3.9, 'only version 3.9 or later supported')
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
        app.Services(clients).close()
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
        callback.assert_called_with(['foo'], ('127.0.0.1', 10001))

        # Check return_service arg
        callback2 = mock.MagicMock(spec_set=True)
        services.assign_callback('EXPINIT', callback2, return_service=True)
        for addr in map(lambda x: x._socket.getsockname(), clients):
            await self.server_1.init('foo', addr=addr)
        self.assertEqual(2, callback2.call_count)
        callback2.assert_called_with(['foo'], ('127.0.0.1', 10001), self.client_2)

        # Check validation
        with self.assertRaises(TypeError):
            services.assign_callback('EXPEND', 'foo')

        # Check clear callbacks
        services.assign_callback('EXPINIT', callback2)
        removed = services.clear_callbacks('EXPINIT', callback)
        self.assertEqual({'client1': 1, 'client2': 1}, removed)
        removed = services.clear_callbacks('EXPINIT')
        self.assertEqual({'client1': 2, 'client2': 2}, removed)

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
