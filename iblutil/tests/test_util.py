import unittest
import types
import typing
from pathlib import Path
import tempfile
import logging
from unittest.mock import patch

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


class TestRrmdir(unittest.TestCase):

    def test_rrmdir(self):
        with self.assertRaises(FileNotFoundError):
            util.rrmdir(Path('/fantasy/path'))
        with tempfile.TemporaryDirectory() as tempdir:
            # nested folders
            folder_level_3 = Path(tempdir).joinpath('folder_level_3')
            folder_level_2 = folder_level_3.joinpath('folder_level_2')
            folder_level_1 = folder_level_2.joinpath('folder_level_1')
            folder_level_0 = folder_level_1.joinpath('folder_level_0')

            # default level = 0, folder contains file - nothing should happen
            folder_level_0.mkdir(parents=True)
            (file := folder_level_0.joinpath('file')).touch()
            self.assertEqual([], util.rrmdir(folder_level_0))
            self.assertTrue(file.exists())

            # default level = 0, folder and all parents are empty
            file.unlink()
            self.assertEqual([folder_level_0], util.rrmdir(folder_level_0))
            self.assertFalse(folder_level_0.exists())
            self.assertTrue(folder_level_1.exists())

            # remove empty folders to level 2
            folder_level_0.mkdir(parents=True)
            removed = util.rrmdir(folder_level_0, levels=2)
            self.assertEqual([folder_level_0, folder_level_1, folder_level_2], removed)
            self.assertFalse(folder_level_2.exists())
            self.assertTrue(folder_level_3.exists())

            # remove empty folders to level 3, with a file in level 2
            folder_level_0.mkdir(parents=True)
            (file := folder_level_2.joinpath('file')).touch()
            removed = util.rrmdir(folder_level_0, levels=3)
            self.assertEqual(removed, [folder_level_0, folder_level_1])
            self.assertFalse(folder_level_1.exists())
            self.assertTrue(file.exists())


class TestDirSize(unittest.TestCase):

    def test_dir_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dir1 = Path(temp_dir)
            dir2 = Path(dir1).joinpath('sub_dir')
            dir2.mkdir()
            file1 = dir1.joinpath('file1')
            file2 = dir2.joinpath('file2')
            file3 = dir2.joinpath('file3')
            with open(file1, 'w') as f1, open(file2, 'w') as f2, open(file3, 'w') as f3:
                f1.write('Old pond')
                f2.write('A frog jumps in')
                f3.write('The sound of water')
            symlink = dir2.joinpath('symlink_file')
            symlink.symlink_to(file1)
            expected = file1.stat().st_size + file2.stat().st_size + file3.stat().st_size
            self.assertEqual(util.dir_size(str(dir1)), expected)
            self.assertEqual(util.dir_size(dir1), expected)
            self.assertEqual(util.dir_size(dir1, True), expected + file1.stat().st_size)


class TestGetMac(unittest.TestCase):

    def test_get_mac(self):
        with patch('iblutil.util.uuid.getnode', return_value=205452675710958):
            self.assertEqual(util.get_mac(), 'BA-DB-AD-C0-FF-EE')


class TestEnsureList(unittest.TestCase):
    """Test ensure_list function."""

    def test_ensure_list(self):
        """Test ensure_list function."""
        x = [1, 2, 3]
        self.assertIs(x, util.ensure_list(x))
        x = tuple(x)
        self.assertIs(x, util.ensure_list(x))
        # Shouldn't iterate over strings or dicts
        x = '123'
        self.assertEqual([x], util.ensure_list(x))
        x = {'1': 1, '2': 2, '3': 3}
        self.assertEqual([x], util.ensure_list(x))
        # Check exclude_type param behaviour
        x = np.array([1, 2, 3])
        self.assertIs(x, util.ensure_list(x))
        self.assertEqual([x], util.ensure_list(x, exclude_type=(np.ndarray)))


class TestListable(unittest.TestCase):
    """Test Listable typing class."""

    def test_listable(self):
        """Test listable type from given class."""
        listable = util.Listable(str)
        self.assertIs(listable, typing.Union[str, typing.Sequence[str]])
        listable = util.Listable(dict)
        self.assertIs(listable, typing.Union[dict, typing.Sequence[dict]])


if __name__ == '__main__':
    unittest.main(exit=False)
