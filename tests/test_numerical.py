import os
import unittest

import numpy as np

import iblutil.numerical as num


class TestFindFirst2D(unittest.TestCase):

    def test_find_first_2d(self):
        # array to test
        mat = np.array([0, 1, 0, 2, 3, 2, 1])

        # test with a value known to be in the array
        val = 3
        i = num.find_first_2d(mat, val)
        if os.name == 'nt':  # Windows returns different datatype for numpy
            self.assertTrue(isinstance(i, np.int32))
        else:
            self.assertTrue(isinstance(i, np.int64))

        # test with a value known to NOT be in the array
        val = 37
        i = num.find_first_2d(mat, val)
        self.assertTrue(isinstance(i, list))
        self.assertTrue(len(i) == 0)


class TestBetweeenSorted(unittest.TestCase):

    def test_between_sorted_single_time(self):
        # test single time, falling right on edges
        t = np.arange(100)
        bounds = [10, 25]
        ind = num.between_sorted(t, bounds)
        assert np.all(t[ind] == np.arange(int(np.ceil(bounds[0])), int(np.floor(bounds[1] + 1))))
        # test single time in between edges
        bounds = [10.4, 25.2]
        ind = num.between_sorted(t, bounds)
        assert np.all(t[ind] == np.arange(np.ceil(bounds[0]), np.floor(bounds[1]) + 1))
        # out of bounds
        ind = num.between_sorted(t, [-5, 800])
        assert np.all(ind)

    def test_between_sorted_multiple_times(self):
        t = np.arange(100)
        # non overlapping ranges
        bounds = np.array([[10.4, 25.2], [67.2, 86.4]])
        ind_ = np.logical_or(num.between_sorted(t, bounds[0]), num.between_sorted(t, bounds[1]))
        ind = num.between_sorted(t, bounds)
        assert np.all(ind == ind_)
        # overlapping ranges
        bounds = np.array([[10.4, 83.2], [67.2, 86.4]])
        ind_ = np.logical_or(num.between_sorted(t, bounds[0]), num.between_sorted(t, bounds[1]))
        ind = num.between_sorted(t, bounds)
        assert np.all(ind == ind_)
        # one range contains the other
        bounds = np.array([[10.4, 83.2], [34, 78]])
        ind_ = np.logical_or(num.between_sorted(t, bounds[0]), num.between_sorted(t, bounds[1]))
        ind = num.between_sorted(t, bounds)
        assert np.all(ind == ind_)
        # case when one range starts exactly where another stops
        bounds = np.array([[10.4, 83.2], [83.2, 84]])
        ind = num.between_sorted(t, bounds)
        ind_ = np.logical_or(num.between_sorted(t, bounds[0]), num.between_sorted(t, bounds[1]))
        assert np.all(ind == ind_)

    def test_between_sorted_out_of_range(self):
        # np searchsorted was returning out of range index when the start time
        # was greater than the max or the end time lower than the min
        bounds = np.array([[-10.4, -3], [10.4, 20], [34, 78]])
        array = np.arange(30)
        assert np.sum(num.between_sorted(array, bounds)) == 10


class TestIsmember(unittest.TestCase):

    def test_ismember2d(self):
        b = np.reshape([0, 0, 0, 1, 1, 1], [3, 2])
        locb = np.array([0, 1, 0, 2, 2, 1])
        lia = np.array([True, True, True, True, True, True, False, False])
        a = np.r_[b[locb, :], np.array([[2, 1], [1, 2]])]
        lia_, locb_ = num.ismember2d(a, b)
        assert np.all(lia == lia_) & np.all(locb == locb_)

    def test_ismember2d_uuids(self):
        nb = 20
        na = 500
        np.random.seed(42)
        a = np.random.randint(0, nb + 3, na)
        b = np.arange(nb)
        lia, locb = num.ismember(a, b)
        bb = np.random.randint(low=np.iinfo(np.int64).min, high=np.iinfo(np.int64).max,
                               size=(nb, 2), dtype=np.int64)
        aa = np.zeros((na, 2), dtype=np.int64)
        aa[lia, :] = bb[locb, :]
        lia_, locb_ = num.ismember2d(aa, bb)
        assert np.all(lia == lia_) & np.all(locb == locb_)
        bb[:, 0] = 0
        aa[:, 0] = 0
        # if the first column is equal, the distinction is to be made on the second\
        assert np.unique(bb[:, 1]).size == nb
        lia_, locb_ = num.ismember2d(aa, bb)
        assert np.all(lia == lia_) & np.all(locb == locb_)

    def test_ismember(self):
        def _check_ismember(a, b, lia_, locb_):
            lia, locb = num.ismember(a, b)
            self.assertTrue(np.all(a[lia] == b[locb]))
            self.assertTrue(np.all(lia_ == lia))
            self.assertTrue(np.all(locb_ == locb))

        b = np.array([0, 1, 3, 4, 4])
        a = np.array([1, 4, 5, 4])
        lia_ = np.array([True, True, False, True])
        locb_ = np.array([1, 3, 3])
        _check_ismember(a, b, lia_, locb_)

        b = np.array([0, 4, 3, 1, 4])
        a = np.array([1, 4, 5, 4])
        lia_ = np.array([True, True, False, True])
        locb_ = np.array([3, 1, 1])
        _check_ismember(a, b, lia_, locb_)

        b = np.array([0, 1, 3, 4])
        a = np.array([1, 4, 5])
        lia_ = np.array([True, True, False])
        locb_ = np.array([1, 3])
        _check_ismember(a, b, lia_, locb_)


class TestWithinRanges(unittest.TestCase):
    def test_within_ranges(self):
        verifiable = num.within_ranges(np.arange(11), [(1, 2), (5, 8)])
        expected = np.array([0, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0], dtype=int)
        np.testing.assert_array_equal(verifiable, expected)

        # Matrix mode
        ranges = np.array([[1, 2], [5, 8]])
        verifiable = num.within_ranges(np.arange(10) + 1, ranges,
                                       labels=np.array([0, 1]), mode='matrix')
        expected = np.array([[1, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                             [0, 0, 0, 0, 1, 1, 1, 1, 0, 0]], dtype=int)
        np.testing.assert_array_equal(verifiable, expected)

        # Test overlap
        verifiable = num.within_ranges(np.arange(11), [(1, 2), (5, 8), (4, 6)],
                                       labels=[0, 1, 1], mode='matrix')
        expected = np.array([[0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                             [0, 0, 0, 0, 1, 2, 2, 1, 1, 0, 0]], dtype=int)
        np.testing.assert_array_equal(verifiable, expected)

        # Vector mode
        verifiable = num.within_ranges(np.arange(10) + 1, ranges, np.array([3, 1]), mode='vector')
        expected = np.array([3, 3, 0, 0, 1, 1, 1, 1, 0, 0], dtype=int)
        np.testing.assert_array_equal(verifiable, expected)

        # Boolean
        verifiable = num.within_ranges(np.arange(11), [(1, 2), (5, 8), (4, 6)], dtype=bool)
        expected = np.array([False, True, True, False, True, True, True, True, True, False, False])
        np.testing.assert_array_equal(verifiable, expected)

        # Edge cases
        verifiable = num.within_ranges(np.arange(11), [])
        expected = np.zeros(11, dtype=int)
        np.testing.assert_array_equal(verifiable, expected)

        with self.assertRaises(ValueError):
            num.within_ranges(np.arange(11), [(1, 2)], mode='array')
