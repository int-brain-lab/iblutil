import asyncio
import logging
import unittest
from unittest import mock
import ipaddress
from functools import partial

from iblutil.io.net import base, app


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
        expected = 'udp://foobar:1001'
        self.assertEqual(expected, base.validate_uri('foobar', resolve_host=False))
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


class TestUDP(unittest.IsolatedAsyncioTestCase):

    last_call = None

    def setUp(self):
        pass
        # from iblutil.util import get_logger
        # get_logger(app.__name__, level=logging.DEBUG)

    async def asyncSetUp(self):
        self.server = await app.EchoProtocol.server('localhost')
        self.client = await app.EchoProtocol.client('localhost')

    async def test_start(self):
        """Tests confirmed send via start command"""
        self.server.assign_callback('expstart', partial(self.__setattr__, 'last_call'))
        with self.assertLogs(app.__name__, logging.INFO) as log:
            await self.client.start('2022-01-01_1_subject')
            expected = 'Received \'[20, "2022-01-01_1_subject"'
            self.assertIn(expected, log.records[-1].message)
        self.assertEqual('2022-01-01_1_subject', self.last_call[0])

    async def test_on_event(self):
        """Test on_event method"""
        task = asyncio.create_task(self.server.on_event('expinit'))
        await self.client.init(42)
        # r = await task
        actual, _ = await task
        self.assertEqual([42], actual)

    def tearDown(self):
        self.client.close()
        self.server.close()


class TestWebSockets(unittest.IsolatedAsyncioTestCase):
    """Test net.app.EchoProtocol with a TCP/IP transport layer"""

    def setUp(self):
        pass
        # from iblutil.util import get_logger
        # get_logger(app.__name__, level=logging.DEBUG)

    async def asyncSetUp(self):
        self.server = await app.EchoProtocol.server('ws://localhost:8888')
        self.client = await app.EchoProtocol.client('ws://localhost:8888')

    async def test_start(self):
        """Tests confirmed send via start command"""
        # TODO Test socket indeed TCP
        with self.assertLogs(app.__name__, logging.INFO) as log:
            await self.client.start('2022-01-01_1_subject')
            expected = 'Received \'[20, "2022-01-01_1_subject"'
            self.assertIn(expected, log.records[-1].message)

    def tearDown(self):
        self.client.close()
        self.server.close()


class TestServices(unittest.IsolatedAsyncioTestCase):
    """Tests for the app.Services class"""

    # def setUp(self):
    #     from iblutil.util import get_logger
    #     get_logger(app.__name__, level=logging.DEBUG)

    async def asyncSetUp(self):
        # On each acquisition PC
        self.server_1 = await app.EchoProtocol.server('localhost', name='server')
        # On main experiment PC
        self.client_1 = await app.EchoProtocol.client('localhost', name='client1')
        self.client_2 = await app.EchoProtocol.client('localhost', name='client2')
        # For some tests we'll need multiple servers (avoids having to run on multiple threads)
        self.server_2 = await app.EchoProtocol.server('localhost:1002', name='server2')
        self.client_3 = await app.EchoProtocol.client('localhost:1002', name='client3')

    async def test_type(self):
        """Test that services are immutable"""
        services = app.Services([self.client_1, self.client_2])
        # Ensure our services stack is immutable
        with self.assertRaises(TypeError):
            services['client2'] = app.EchoProtocol
        with self.assertRaises(TypeError):
            services.pop('client1')

    async def test_close(self):
        """Test Services.close method"""
        clients = [self.client_1, self.client_2]
        assert all(x.is_connected for x in clients)
        app.Services(clients).close()
        self.assertTrue(not any(x.is_connected for x in clients))

    async def test_assign(self):
        """Tests for Services.assign_callback and Services.clear_callbacks"""
        # Assign a callback for an event
        callback = mock.MagicMock()
        clients = (self.client_1, self.client_2)
        services = app.Services(clients)
        services.assign_callback('EXPINIT', callback)

        for addr in map(lambda x: x._socket.getsockname(), clients):
            await self.server_1.init('foo', addr=addr)

        self.assertEqual(2, callback.call_count)
        callback.assert_called_with(['foo'], ('127.0.0.1', 1001))

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
            await asyncio.sleep(.1)  # FIXME Should be able to somehow used loop.call_soon
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

    @unittest.skip('Unfinished')
    async def test_await_all(self):
        """Test for Services.await_all method"""
        pass

    def tearDown(self):
        self.client_1.close()
        self.client_2.close()
        self.server_1.close()
        self.server_2.close()
        self.client_3.close()


if __name__ == '__main__':
    from iblutil.util import get_logger
    get_logger(app.__name__, level=logging.DEBUG)

    unittest.main()
