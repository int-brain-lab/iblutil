import unittest
import tempfile
from pathlib import Path
import types

import numpy as np

from iblutil import util


class TestBunch(unittest.TestCase):

    def test_sync(self):
        """
        This test is just to document current use in libraries in case of refactoring
        """
        sd = util.Bunch({'label': 'toto', 'ap': None, 'lf': 8})
        self.assertTrue(sd['label'] is sd.label)
        self.assertTrue(sd['ap'] is sd.ap)
        self.assertTrue(sd['lf'] is sd.lf)

    def test_bunch_io(self):
        a = np.random.rand(50, 1)
        b = np.random.rand(50, 1)
        abunch = util.Bunch({'a': a, 'b': b})

        with tempfile.TemporaryDirectory() as td:
            npz_file = Path(td).joinpath('test_bunch.npz')
            abunch.save(npz_file)
            another_bunch = util.Bunch.load(npz_file)
            [self.assertTrue(np.all(abunch[k]) == np.all(another_bunch[k])) for k in abunch]
            npz_filec = Path(td).joinpath('test_bunch_comp.npz')
            abunch.save(npz_filec, compress=True)
            another_bunch = util.Bunch.load(npz_filec)
            [self.assertTrue(np.all(abunch[k]) == np.all(another_bunch[k])) for k in abunch]
            with self.assertRaises(FileNotFoundError):
                util.Bunch.load(Path(td) / 'fake.npz')


class TestFlatten(unittest.TestCase):

    def test_flatten(self):
        x = (1, 2, 3, [1, 2], 'string', 0.1, {1: None}, [[1, 2, 3], {1: 1}, 1])
        self.assertEqual(util._iflatten(x), util.flatten(x))
        self.assertEqual(util.flatten(x)[:5], [1, 2, 3, 1, 2])
        self.assertEqual(list(util._gflatten(x)), list(util.flatten(x, generator=True)))
        self.assertIsInstance(util.flatten(x, generator=True), types.GeneratorType)


class TestRangeStr(unittest.TestCase):

    def test_range_str(self):
        x = [1, 2, 3, 4, 5, 6, 7, 8, 12, 17]
        self.assertEqual(util.range_str(x), '1-8, 12 & 17')

        x = [0, 6, 7, 10, 11, 12, 30, 30]
        self.assertEqual(util.range_str(x), '0, 6-7, 10-12 & 30')

        self.assertEqual(util.range_str([]), '')


if __name__ == "__main__":
    unittest.main(exit=False)
