import unittest
import types
from pathlib import Path
import tempfile
import logging

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


class TestLogger(unittest.TestCase):
    log_name = '_foobar'

    def test_no_duplicates(self):
        log = util.get_logger('gnagna')
        assert len(log.handlers) == 1
        log = util.get_logger('gnagna')
        assert len(log.handlers) == 1

    def test_file_handler_setup(self):
        # NB: this doesn't work with a context manager, the handlers get all confused
        # with the fake file object
        import tempfile
        with tempfile.TemporaryDirectory() as tn:
            file_log = Path(tn).joinpath('log.txt')
            log = util.get_logger('tutu', file=file_log, no_color=True)
            log.info('toto')
            # the purpose of the test is to test that the logger/handler has not been
            # duplicated so after 2 calls we expect 2 lines
            log = util.get_logger('tutu', file=file_log)
            log.info('tata')
            while True:
                handlers = log.handlers
                if len(handlers) == 0:
                    break
                handlers[0].close()
                log.removeHandler(handlers[0])
            with open(file_log) as fp:
                lines = fp.readlines()
            assert (len(lines) == 3)

    def test_file_handler_stand_alone(self):
        """Test for ibllib.misc.log_to_file"""
        log_path = Path.home().joinpath('.ibl_logs', self.log_name)
        log_path.unlink(missing_ok=True)
        test_log = util.log_to_file(filename=self.log_name, name=self.log_name)
        test_log.info('foobar')

        # Should have created a log file and written to it
        self.assertTrue(log_path.exists())
        with open(log_path, 'r') as f:
            logged = f.read()
        self.assertIn('foobar', logged)

    def tearDown(self) -> None:
        # Before we can delete the test log file we must close the file handler
        test_log = logging.getLogger(self.log_name)
        for handler in test_log.handlers:
            handler.close()
            test_log.removeHandler(handler)
        Path.home().joinpath('.ibl_logs', self.log_name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(exit=False)
