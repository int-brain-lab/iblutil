import logging
import unittest
import ipaddress

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


class TestUDP(unittest.IsolatedAsyncioTestCase):

    last_call = None

    def setUp(self):
        pass
        # from iblutil.util import get_logger
        # get_logger(app.__name__, level=logging.DEBUG)

    async def asyncSetUp(self):
        self.server = await app.EchoProtocol.server('localhost')
        self.client = await app.EchoProtocol.client('localhost')

    def _update_call(self, data, addr):
        self.last_call = (data, addr)

    async def test_start(self):
        """Tests confirmed send via start command"""
        self.server.assign_callback('expstart', self._update_call)
        with self.assertLogs(app.__name__, logging.INFO) as log:
            await self.client.start('2022-01-01_1_subject')
            expected = 'Received \'["EXPSTART", "2022-01-01_1_subject"]\''
            self.assertIn(expected, log.records[-1].message)
        self.assertEqual('2022-01-01_1_subject', self.last_call[0])

    def tearDown(self):
        self.client.close()
        self.server.close()


class TestWebSockets(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        pass
        # from iblutil.util import get_logger
        # get_logger(app.__name__, level=logging.DEBUG)

    async def asyncSetUp(self):
        self.server = await app.EchoProtocol.server('ws://localhost:8888')
        self.client = await app.EchoProtocol.client('ws://localhost:8888')

    async def test_start(self):
        """Tests confirmed send via start command"""
        with self.assertLogs(app.__name__, logging.INFO) as log:
            await self.client.start('2022-01-01_1_subject')
            expected = 'Received \'["EXPSTART", "2022-01-01_1_subject"]\''
            self.assertIn(expected, log.records[-1].message)

    def tearDown(self):
        self.client.close()
        self.server.close()


if __name__ == '__main__':
    unittest.main()
