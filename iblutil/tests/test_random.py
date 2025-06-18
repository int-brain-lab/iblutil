import unittest

import iblutil.random


class TestRandom(unittest.TestCase):

    def test_silly_name(self):
        name = iblutil.random.sillyname()
        assert len(name) > 3, 'Generated name is empty'
