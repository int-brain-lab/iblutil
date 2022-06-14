import unittest
from unittest import mock
import uuid
import tempfile
import os
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main(exit=False, verbosity=2)
