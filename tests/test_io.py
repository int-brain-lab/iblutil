import unittest
from unittest import mock
import uuid
import tempfile
import os
from pathlib import Path
import json
import asyncio

import numpy as np

from iblutil.io.parquet import uuid2np, np2uuid, np2str, str2np
from iblutil.io import params
import iblutil.io.jsonable as jsonable
from iblutil.numerical import intersect2d, ismember2d, ismember


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


if __name__ == '__main__':
    unittest.main(exit=False, verbosity=2)
