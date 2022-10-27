import unittest
import types
from pathlib import Path
import tempfile
import logging

import numpy as np

from iblutil import util


class TestBunch(unittest.TestCase):

    def test_copy(self):
        """Test Bunch.copy method."""
        # Expect shallow copy by default
        bunch_one = util.Bunch({'test': np.arange(5)})
        bunch_two = bunch_one.copy()
        self.assertIsNot(bunch_one, bunch_two)
        bunch_two['test'][0] = 5
        self.assertEqual(5, bunch_one['test'][0])
        # Expect deep copy
        bunch_one = util.Bunch({'test': np.arange(5)})
        bunch_two = bunch_one.copy(deep=True)
        self.assertIsNot(bunch_one, bunch_two)
        bunch_two['test'][0] = 5
        self.assertNotEqual(5, bunch_one['test'][0])

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
        log = util.setup_logger('gnagna')
        self.assertEqual(1, len(log.handlers))
        log = util.setup_logger('gnagna')
        self.assertEqual(1, len(log.handlers))

    def test_file_handler_setup(self):
        # NB: this doesn't work with a context manager, the handlers get all confused
        # with the fake file object
        with tempfile.TemporaryDirectory() as tn:
            file_log = Path(tn).joinpath('log.txt')
            log = util.setup_logger('tutu', file=file_log, no_color=True, level=20)
            log.info('toto')
            # the purpose of the test is to test that the logger/handler has not been
            # duplicated so after 2 calls we expect 2 lines
            log = util.setup_logger('tutu', file=file_log, level=20)
            log.info('tata')
            while True:
                handlers = log.handlers
                if len(handlers) == 0:
                    break
                handlers[0].close()
                log.removeHandler(handlers[0])
            with open(file_log) as fp:
                lines = fp.readlines()
            self.assertEqual(3, len(lines))

    def test_file_handler_stand_alone(self):
        """Test for ibllib.misc.log_to_file"""
        log_path = Path.home().joinpath('.ibl_logs', self.log_name)
        log_path.unlink(missing_ok=True)
        test_log = util.log_to_file(filename=self.log_name, log=self.log_name)
        test_log.level = 20
        test_log.info('foobar')

        # Should have created a log file and written to it
        self.assertTrue(log_path.exists())
        with open(log_path, 'r') as f:
            logged = f.read()
        self.assertIn('foobar', logged)

    def test_file_handler_log_input(self):
        """Test ibllib.misc.log_to_file accepts log object as input"""
        # Should word with log as input
        test_log = logging.getLogger(self.log_name)
        test_log.level = 20
        util.log_to_file(test_log).info('hello world!')
        log_path = Path.home().joinpath('.ibl_logs', self.log_name)
        self.assertTrue(log_path.exists())
        with open(log_path, 'r') as f:
            logged = f.read()
        self.assertIn('hello world', logged)

    def tearDown(self) -> None:
        # Before we can delete the test log file we must close the file handler
        test_log = logging.getLogger(self.log_name)
        for handler in test_log.handlers:
            handler.close()
            test_log.removeHandler(handler)
        Path.home().joinpath('.ibl_logs', self.log_name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(exit=False)
