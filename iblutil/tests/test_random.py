import unittest

import hashlib
import iblutil.random


class TestRandom(unittest.TestCase):
    def test_silly_name(self):
        name = iblutil.random.sillyname()
        assert len(name) > 3, 'Generated name is empty'

    def test_from_hash(self):
        h = hashlib.md5('6a317f9b-587a-4524-8528-677744a8134f.sdfi'.encode())
        self.assertEqual('powerful-yellowgreen-lemming', iblutil.random.name_from_hash(h))
