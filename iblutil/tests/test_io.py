import unittest
from unittest import mock
import uuid
import tempfile
import os
from pathlib import Path
import json
import asyncio

import numpy as np
import pandas as pd

from iblutil.io.binary import load_as_dataframe, convert_to_parquet, write_array
from iblutil.io.parquet import uuid2np, np2uuid, np2str, str2np
from iblutil.io import params
import iblutil.io.jsonable as jsonable
from iblutil.numerical import intersect2d, ismember2d, ismember


class TestBinary(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir_path = Path(self.temp_dir.name)

        self.temp_bin_path = self.temp_dir_path.joinpath('data.bin')
        self.dtype = np.dtype([('field1', np.int32), ('field2', np.float32)])
        sample_data = np.array([(1, 1.1), (2, 2.2), (3, 3.3)], dtype=self.dtype)
        sample_data.tofile(self.temp_bin_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_as_dataframe(self):
        # Test loading the binary file as a DataFrame
        df = load_as_dataframe(self.temp_bin_path, self.dtype)
        self.assertEqual(len(df), 3)
        self.assertListEqual(list(df.columns), ['field1', 'field2'])
        assert np.array_equal(df['field1'].values, np.array([1, 2, 3], dtype=np.int32))
        assert np.array_equal(df['field2'].values, np.array([1.1, 2.2, 3.3], dtype=np.float32))

    def test_load_as_dataframe_count(self):
        # Test loading the binary file as a DataFrame (only first row)
        df = load_as_dataframe(self.temp_bin_path, self.dtype, count=1)
        self.assertEqual(len(df), 1)
        self.assertListEqual(list(df.columns), ['field1', 'field2'])
        assert np.array_equal(df['field1'].values, np.array([1], dtype=np.int32))
        assert np.array_equal(df['field2'].values, np.array([1.1], dtype=np.float32))

    def test_load_as_dataframe_offset(self):
        # Test loading the binary file as a DataFrame (with offset)
        df = load_as_dataframe(self.temp_bin_path, self.dtype, offset=8)
        self.assertEqual(len(df), 2)
        self.assertListEqual(list(df.columns), ['field1', 'field2'])
        assert np.array_equal(df['field1'].values, np.array([2, 3], dtype=np.int32))
        assert np.array_equal(df['field2'].values, np.array([2.2, 3.3], dtype=np.float32))

    def test_load_as_dataframe_file_not_found(self):
        # Test for FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            load_as_dataframe('non_existent_file.bin', self.dtype)

    def test_load_as_dataframe_incorrect_dtype(self):
        # Test for ValueError on incorrect dtype
        with self.assertRaises(ValueError):
            load_as_dataframe(self.temp_bin_path, int)
        with self.assertRaises(ValueError):
            load_as_dataframe(self.temp_bin_path, np.int32)

    def test_load_as_dataframe_is_a_directory(self):
        # Create a temporary directory and test if it raises IsADirectoryError
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(IsADirectoryError):
                load_as_dataframe(temp_dir, self.dtype)

    def test_convert_to_parquet(self):
        # Test converting the binary file to a Parquet file
        parquet_path = convert_to_parquet(self.temp_bin_path, self.dtype)
        self.assertTrue(parquet_path.exists())
        self.assertEqual(parquet_path.suffix, '.pqt')

        # Load the Parquet file back into a DataFrame and check its contents
        df_parquet = pd.read_parquet(parquet_path)
        self.assertEqual(len(df_parquet), 3)
        self.assertListEqual(list(df_parquet.columns), ['field1', 'field2'])
        assert np.array_equal(df_parquet['field1'].values, np.array([1, 2, 3], dtype=np.int32))
        assert np.array_equal(df_parquet['field2'].values, np.array([1.1, 2.2, 3.3], dtype=np.float32))

    def test_convert_to_parquet_delete(self):
        # Test conversion with deletion of the binary file
        parquet_path = convert_to_parquet(self.temp_bin_path, self.dtype, delete_bin_file=True)
        self.assertTrue(parquet_path.exists())
        self.assertFalse(self.temp_bin_path.exists())  # Check if the binary file was deleted

    def test_convert_to_parquet_exists(self):
        # Test conversion with when pqt file exists already
        self.temp_bin_path.with_suffix('.pqt').touch()
        with self.assertRaises(FileExistsError):
            convert_to_parquet(self.temp_bin_path, self.dtype, delete_bin_file=True)

    def test_write_array_invalid_dtype(self):
        # Test with an invalid dtype
        with self.assertRaises(ValueError):
            write_array(self.temp_bin_path, [1], np.dtype('float'))

    def test_write_array_too_many_dimensions(self):
        # Test with an array that has more than two dimensions
        with self.assertRaises(ValueError):
            write_array(self.temp_bin_path, [[[1, 2]], [[3, 4]]], self.dtype)

    def test_write_array_shape_mismatch(self):
        # Test with an array whose last dimension does not match dtype fields
        self.temp_bin_path.unlink()
        with self.assertRaises(ValueError):
            write_array(self.temp_bin_path, [1], self.dtype)

    def test_write_array_file_exists(self):
        # Test with a file path that already exists
        with self.assertRaises(FileExistsError):
            write_array(self.temp_bin_path, [1, 2], self.dtype)

    def test_write_array_invalid_file_type(self):
        # Test with an invalid file identifier
        with self.assertRaises(TypeError):
            write_array(123, [1, 2], self.dtype)

    def test_write_array(self):
        # Test that data can be written
        with self.temp_bin_path.open('wb') as f:
            write_array(f, [42, 42], self.dtype)
        data = np.fromfile(self.temp_bin_path, dtype=self.dtype)
        self.assertEqual(data.tolist(), [(42, 42.0)])


class TestParquet(unittest.TestCase):

    def test_uuids_conversions(self):
        str_uuid = 'a3df91c8-52a6-4afa-957b-3479a7d0897c'
        one_np_uuid = np.array([-411333541468446813, 8973933150224022421])
        two_np_uuid = np.tile(one_np_uuid, [2, 1])
        # array gives a list
        self.assertTrue(all(map(lambda x: x == str_uuid, np2str(two_np_uuid))))
        # single uuid gives a string
        self.assertTrue(np2str(one_np_uuid) == str_uuid)
        # list uuids with some None entries
        uuid_list = ['bc74f49f33ec0f7545ebc03f0490bdf6', 'c5779e6d02ae6d1d6772df40a1a94243',
                     None, '643371c81724378d34e04a60ef8769f4']
        assert np.all(str2np(uuid_list)[2, :] == 0)

    def test_uuids_intersections(self):
        ntotal = 500
        nsub = 17
        nadd = 3

        eids = uuid2np([uuid.uuid4() for _ in range(ntotal)])

        np.random.seed(42)
        isel = np.floor(np.argsort(np.random.random(nsub)) / nsub * ntotal).astype(np.int16)
        sids = np.r_[eids[isel, :], uuid2np([uuid.uuid4() for _ in range(nadd)])]
        np.random.shuffle(sids)

        # check the intersection
        v, i0, i1 = intersect2d(eids, sids)
        assert np.all(eids[i0, :] == sids[i1, :])
        assert np.all(np.sort(isel) == np.sort(i0))

        v_, i0_, i1_ = np.intersect1d(eids[:, 0], sids[:, 0], return_indices=True)
        assert np.setxor1d(v_, v[:, 0]).size == 0
        assert np.setxor1d(i0, i0_).size == 0
        assert np.setxor1d(i1, i1_).size == 0

        for a, b in zip(ismember2d(sids, eids), ismember(sids[:, 0], eids[:, 0])):
            assert np.all(a == b)

        # check conversion to numpy back and forth
        uuids = [uuid.uuid4() for _ in np.arange(4)]
        np_uuids = uuid2np(uuids)
        assert np2uuid(np_uuids) == uuids


class TestParams(unittest.TestCase):

    @mock.patch('sys.platform', 'linux')
    def test_set_hidden(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td).joinpath('file')
            file.touch()
            hidden_file = params.set_hidden(file, True)
            self.assertFalse(file.exists())
            self.assertTrue(hidden_file.exists())
            self.assertEqual(hidden_file.name, '.file')

            params.set_hidden(hidden_file, False)
            self.assertFalse(hidden_file.exists())
            self.assertTrue(file.exists())


class TestFileLock(unittest.IsolatedAsyncioTestCase):
    tmp = None

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(tmp.name)
        cls.addClassCleanup(tmp.cleanup)

    def setUp(self):
        self.file = self.tmp / 'foo.bar'
        self.addCleanup(self.file.unlink, missing_ok=True)
        self.lock_file = self.file.with_suffix('.lock')
        self.addCleanup(self.lock_file.unlink, missing_ok=True)

    @mock.patch('iblutil.io.params.time.sleep')
    def test_file_lock_sync(self, sleep_mock):
        """Test synchronous FileLock context manager."""
        # Check input validation
        self.assertRaises(ValueError, params.FileLock, self.file, timeout_action='foo')

        # Check behaviour when lock file doesn't exist (i.e. no other process writing to file)
        assert not self.lock_file.exists()
        with params.FileLock(self.file, timeout_action='raise'):
            self.assertTrue(self.lock_file.exists(), 'Failed to create lock file')
        self.assertFalse(self.lock_file.exists(), 'Failed to remove lock file upon exit of context manager')
        sleep_mock.assert_not_called()  # no file present so no need to sleep

        # Check behaviour when lock file present and not removed by other process
        self.lock_file.touch()
        assert self.lock_file.exists()
        lock = params.FileLock(self.file, timeout_action='raise')
        with self.assertLogs('iblutil.io.params', 10) as lg:
            self.assertRaises(TimeoutError, lock.__enter__)
        msg = next((x.getMessage() for x in lg.records if x.levelno == 10), None)
        self.assertEqual('file lock contents: <empty>', msg)
        # should try 5 attempts by default; default total timeout is 10 seconds so should sleep 5x for 2 seconds each
        expected_attempts = 5
        sleep_mock.assert_called_with(2)
        self.assertEqual(expected_attempts, sleep_mock.call_count)
        self.assertEqual(expected_attempts, len([x for x in lg.records if x.levelno == 20]))
        msg = next(x.getMessage() for x in lg.records if x.levelno == 20)
        self.assertRegex(msg, 'file lock found, waiting 2.00 seconds')

        # Check delete timeout action
        assert self.lock_file.exists()
        with self.assertLogs('iblutil.io.params', 10) as lg, \
                params.FileLock(self.file, timeout_action='delete'):
            # Should have replaced empty lock file with timestamped one
            self.assertTrue(self.lock_file.exists())
            with open(self.lock_file, 'r') as fp:
                lock_info = json.load(fp)
            self.assertCountEqual(('datetime', 'hostname'), lock_info)
        self.assertFalse(self.lock_file.exists(), 'Failed to remove lock file upon exit of context manager')
        self.assertRegex(lg.records[-1].getMessage(), 'stale file lock found, deleting')

    async def _mock(self, obj):
        """
        Add side effect to mock object that awaits a future.

        This is required because async lambdas are not supported.

        Parameters
        ----------
        obj : unittest.mock.AsyncMock
            An asynchronous mock object to install side effect for.

        Returns
        -------
        asyncio.Future
            A future awaited by input mock object.
        """
        fut = asyncio.get_event_loop().create_future()
        self.addCleanup(fut.cancel)

        async def wait(_):
            return await fut

        obj.side_effect = wait
        return fut

    @mock.patch('iblutil.io.params.asyncio.sleep')
    async def test_file_lock_async(self, sleep_mock):
        """Test asynchronous FileLock context manager."""
        # Check behaviour when lock file doesn't exist (i.e. no other process writing to file)
        assert not self.lock_file.exists()
        async with params.FileLock(self.file, timeout_action='raise'):
            self.assertTrue(self.lock_file.exists(), 'Failed to create lock file')
        self.assertFalse(self.lock_file.exists(), 'Failed to remove lock file upon exit of context manager')
        sleep_mock.assert_not_called()  # no file present so no need to sleep

        # Check behaviour when lock file present and not removed by other process
        self.lock_file.touch()
        assert self.lock_file.exists()
        lock = params.FileLock(self.file, timeout=1e-3, timeout_action='raise')
        # The loop that checks the lock file is too fast when async.sleep is mocked so adding a side
        # effect that awaits a future that's never set allows the timeout code to execute.
        await self._mock(sleep_mock)

        with self.assertLogs('iblutil.io.params', 10) as lg, self.assertRaises(asyncio.TimeoutError):
            await lock.__aenter__()
            # fut = asyncio.get_running_loop().create_future()
            # with mock.patch.object(lock, '_lock_check_async', return_value) as m:

            # async with params.FileLock(self.file, timeout=1e-3, timeout_action='raise') as lock:
            #     ...
        sleep_mock.assert_awaited_with(lock._async_poll_freq)
        msg = next((x.getMessage() for x in lg.records if x.levelno == 10), None)
        self.assertEqual('file lock contents: <empty>', msg)

        # Check remove timeout action
        assert self.lock_file.exists()
        await self._mock(sleep_mock)
        with self.assertLogs('iblutil.io.params', 10) as lg:
            async with params.FileLock(self.file, timeout=1e-5, timeout_action='delete'):
                # Should have replaced empty lock file with timestamped one
                self.assertTrue(self.lock_file.exists())
                with open(self.lock_file, 'r') as fp:
                    lock_info = json.load(fp)
            self.assertCountEqual(('datetime', 'hostname', 'pid'), lock_info)
        self.assertFalse(self.lock_file.exists(), 'Failed to remove lock file upon exit of context manager')


class TestsJsonable(unittest.TestCase):
    def setUp(self) -> None:
        self.tfile = tempfile.NamedTemporaryFile(delete=False)

    def testReadWrite(self):
        data = [{'a': 'thisisa', 'b': 1, 'c': [1, 2, 3]},
                {'a': 'thisisb', 'b': 2, 'c': [2, 3, 4]}]
        jsonable.write(self.tfile.name, data)
        data2 = jsonable.read(self.tfile.name)
        self.assertEqual(data, data2)
        jsonable.append(self.tfile.name, data)
        data3 = jsonable.read(self.tfile.name)
        self.assertEqual(data + data, data3)

    def tearDown(self) -> None:
        self.tfile.close()
        os.unlink(self.tfile.name)


class TestLoadTaskData(unittest.TestCase):
    def test_load_task_jsonable(self):
        jsonable_file = Path(__file__).parent.joinpath('fixtures', 'task_data_short.jsonable')
        trials_table, bpod_data = jsonable.load_task_jsonable(jsonable_file)
        assert trials_table.shape[0] == 2
        assert len(bpod_data) == 2

    def test_load_task_jsonable_partial(self):
        jsonable_file = Path(__file__).parent.joinpath('fixtures', 'task_data_short.jsonable')
        with open(jsonable_file) as fp:
            fp.readline()
            offset = fp.tell()
        trials_table, bpod_data = jsonable.load_task_jsonable(jsonable_file, offset=offset)

        trials_table_full, bpod_data_full = jsonable.load_task_jsonable(jsonable_file)
        for c in trials_table.columns:
            if not np.isnan(trials_table[c][0]):
                np.testing.assert_equal(trials_table_full[c].values[-1], trials_table[c][0])

        assert bpod_data_full[-1] == bpod_data[0]


if __name__ == '__main__':
    unittest.main(exit=False, verbosity=2)
