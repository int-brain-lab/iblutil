import numpy as np
import unittest

from iblutil.spacer import Spacer


class TestSpacer(unittest.TestCase):

    def test_spacer(self):
        spacer = Spacer(dt_start=.02, dt_end=.4, n_pulses=8, tup=.05)
        np.testing.assert_equal(spacer.times.size, 15)
        sig = spacer.generate_template(fs=1000)
        ac = np.correlate(sig, sig, 'full') / np.sum(sig**2)
        # import matplotlib.pyplot as plt
        # plt.plot(ac)
        # plt.show()
        ac[sig.size - 100: sig.size + 100] = 0  # remove the main peak
        # the autocorrelation side lobes should be less than 30%
        assert np.max(ac) < .3

    def test_find_spacers(self):
        """Generates a fake signal with 2 spacers and finds them"""
        fs = 1000
        spacer = Spacer(dt_start=.02, dt_end=.4, n_pulses=8, tup=.05)
        start_times = [4.38, 96.58]
        template = spacer.generate_template(fs)
        signal = np.zeros(int(start_times[-1] * fs + template.size * 2))
        for start_time in start_times:
            signal[int(start_time * fs): int(start_time * fs) + template.size] = template
        spacer_times = spacer.find_spacers(signal, fs=fs)
        np.testing.assert_allclose(spacer_times, start_times)


class TestSpacersFromFronts(unittest.TestCase):
    """Tests for Spacer.find_spacers_from_fronts"""
    def setUp(self) -> None:
        self.spacer_1 = Spacer()
        self.spacer_2 = Spacer(n_pulses=12, tup=.1)

    def test_extract_spacers(self):
        """Test Spacer.find_spacers_from_fronts with usual spacer"""
        # Single spacer, nothing else
        Fs = 1000
        template = self.spacer_1.generate_template(fs=Fs)
        ind, val = self.to_fronts(template)
        t0 = 15.  # start at 15 seconds
        times = ind * 1 / Fs + t0
        fronts = {'times': times, 'polarities': val}
        t = self.spacer_1.find_spacers_from_fronts(fronts)
        self.assertEqual(1, len(t))
        np.testing.assert_allclose(t, t0, rtol=1e-3)

        # Add a second spacer with unrelated pulses in between
        signal_times, p = self._random_pulses(t0=t0 + 1 / Fs * template.size + np.random.rand())
        fronts['times'] = np.concatenate([times, signal_times, ind * 1 / Fs + t0 + signal_times[-1]])
        fronts['polarities'] = np.concatenate([val, p, val])

        # Expect 2 spacer times
        t = self.spacer_1.find_spacers_from_fronts(fronts)
        self.assertEqual(2, len(t))
        np.testing.assert_allclose(t, [t0, signal_times[-1] + t0], rtol=1e-3)

    def test_empty(self):
        """Test behaviour when a signal is passed in that doesn't contain any spacers."""
        # Make some random pulses
        times, polarities = self._random_pulses()
        fronts = {'times': times, 'polarities': polarities}
        self.assertEqual(0, self.spacer_1.find_spacers_from_fronts(fronts).size)

    def test_noise(self):
        """Test whether it can deal with noise in the spacer signal.

        NB: Currently any noise will result in no spacer detection.
        """
        Fs = 1000
        template = self.spacer_1.generate_template(fs=Fs)
        ind, val = self.to_fronts(template)
        t0 = 15.  # start at 15 seconds
        times = ind * 1 / Fs + t0

        # Add some noise to the signal
        noise_times, noise_p = self._random_pulses(t0, 4, pw=.005, t_max=times[-1] - t0)
        fronts = {
            'times': np.sort(np.concatenate([times, noise_times])),
            'polarities': np.concatenate([val, noise_p])
        }

        t = self.spacer_1.find_spacers_from_fronts(fronts)
        self.assertEqual(0, len(t))  # NB This could one day return 1
        np.testing.assert_allclose(t, t0, rtol=1e-3)

    def test_custom_spacer_extract(self):
        """Test is different spacer parameters"""
        Fs = 1200  # a non-default sampling rate
        template = self.spacer_2.generate_template(fs=Fs)
        ind, val = self.to_fronts(template)
        t0 = 15.  # start at 15 seconds
        fronts = {'times': ind * 1 / Fs + t0, 'polarities': val}
        t = self.spacer_2.find_spacers_from_fronts(fronts, fs=Fs)
        self.assertEqual(1, len(t))
        np.testing.assert_allclose(t, t0, rtol=1e-3)

    @staticmethod
    def _random_pulses(t0=0., n=50, pw=None, t_max=200):
        if not pw:
            times = np.sort(np.random.randint(0, t_max, n) + np.random.rand(n)) + t0
        else:
            times = np.random.randint(0, t_max, n) + np.random.rand(n) + t0
            times = np.sort(np.concatenate([times, times + pw]))
        polarities = np.ones_like(times)
        polarities[1::2] = -1.
        return times, polarities

    @staticmethod
    def to_fronts(signal):
        """
        Detects Rising and Falling edges of a voltage signal, returns indices and polarities.

        Parameters
        ----------
        signal : numpy.array
            Array on which to compute RMS

        Returns
        -------
        numpy.array
            Array of indices
        numpy.array
            Array of polarities {1, -1}

        """
        d = np.diff(signal)
        ind = np.array(np.where(np.abs(d) >= 1))
        sign = d[tuple(ind)]
        ind[-1] += 1
        return (ind[0], sign) if len(ind) == 1 else (ind, sign)
