import math
import os
from enum import Enum
from pathlib import Path
from textwrap import wrap
from typing import List, Callable, Tuple, Optional

import librosa
import matplotlib.pyplot as plt
from lazy import lazy
from matplotlib import ticker
from matplotlib.ticker import ScalarFormatter
from numpy import ndarray, mean, std, vectorize, dot


class SpectrogramFrequencyScale(Enum):
    linear = "linear"
    mel = "mel"


class SpectrogramType(Enum):
    power = "power"
    amplitude = "amplitude"
    power_level = "power level"


class ScalarFormatterWithUnit(ScalarFormatter):
    def __init__(self, unit: str):
        super().__init__()
        self.unit = unit

    def __call__(self, x, pos=None) -> str:
        return super().__call__(x, pos) + self.unit


def z_normalize(array: ndarray) -> ndarray:
    return (array - mean(array)) / std(array)


class LabeledExample:
    def __init__(self, id: str,
                 get_raw_sound_and_sample_rate: Callable[[], Tuple[ndarray, int]],
                 label: Optional[str],
                 fourier_window_length: int = 512,
                 hop_length: int = 128,
                 asserted_sample_rate: int = 16000):
        # The default values for hop_length and fourier_window_length are powers of 2 near the values specified in the wave2letter paper.
        self.id = id
        self.get_raw_sound_and_sample_rate = get_raw_sound_and_sample_rate
        self.label = label
        self.assert_sample_rate = asserted_sample_rate
        self.hop_length = hop_length
        self.fourier_window_length = fourier_window_length

    @staticmethod
    def from_file(audio_file: Path, id: Optional[str] = None,
                  label_from_id: Callable[[str], Optional[str]] = lambda id: None,
                  fourier_window_length: int = 512,
                  hop_length: int = 128,
                  asserted_sample_rate: int = 16000) -> 'LabeledExample':
        if id is None:
            id = os.path.splitext(audio_file.name)[0]

        return LabeledExample(id=id, get_raw_sound_and_sample_rate=lambda: librosa.load(str(audio_file), sr=None),
                              label=label_from_id(id),
                              fourier_window_length=fourier_window_length,
                              hop_length=hop_length,
                              asserted_sample_rate=asserted_sample_rate)

    @lazy
    def raw_audio_and_sample_rate(self) -> (ndarray, int):
        y, sr = self.get_raw_sound_and_sample_rate()

        if self.assert_sample_rate is not None:
            assert (self.assert_sample_rate == sr)

        return y, sr

    @lazy
    def raw_audio(self) -> ndarray:
        return self.raw_audio_and_sample_rate[0]

    @lazy
    def sample_rate(self) -> int:
        return self.raw_audio_and_sample_rate[1]

    def _power_spectrogram(self) -> ndarray:
        return self._amplitude_spectrogram() ** 2

    def _amplitude_spectrogram(self) -> ndarray:
        return abs(self._complex_spectrogram())

    def _complex_spectrogram(self) -> ndarray:
        return librosa.stft(y=self.raw_audio, n_fft=self.fourier_window_length, hop_length=self.hop_length)

    def mel_frequencies(self) -> List[float]:
        # according to librosa.filters.mel
        return librosa.mel_frequencies(128 + 2, fmax=self.sample_rate / 2)

    def _convert_spectrogram_to_mel_scale(self, linear_frequency_spectrogram: ndarray) -> ndarray:
        return dot(librosa.filters.mel(sr=self.sample_rate, n_fft=self.fourier_window_length),
                   linear_frequency_spectrogram)

    def plot_raw_audio(self) -> None:
        self._plot_audio(self.raw_audio)

    def _plot_audio(self, audio: ndarray) -> None:
        plt.title(str(self))
        plt.xlabel("time / samples (sample rate {}Hz)".format(self.sample_rate))
        plt.ylabel("y")
        plt.plot(audio)
        plt.show()

    def show_spectrogram(self, type: SpectrogramType = SpectrogramType.power_level):
        self.prepare_spectrogram_plot(type)
        plt.show()

    def save_spectrogram(self, target_directory: Path,
                         type: SpectrogramType = SpectrogramType.power_level,
                         frequency_scale: SpectrogramFrequencyScale = SpectrogramFrequencyScale.linear) -> Path:
        self.prepare_spectrogram_plot(type, frequency_scale)
        path = Path(target_directory, "{}_{}{}_spectrogram.png".format(self.id,
                                                                       "mel_" if frequency_scale == SpectrogramFrequencyScale.mel else "",
                                                                       type.value.replace(" ", "_")))

        plt.savefig(str(path))
        return path

    def highest_detectable_frequency(self) -> float:
        return self.sample_rate / 2

    def duration_in_s(self) -> float:
        return self.raw_audio.shape[0] / self.sample_rate

    def spectrogram(self, type: SpectrogramType = SpectrogramType.power_level,
                    frequency_scale: SpectrogramFrequencyScale = SpectrogramFrequencyScale.linear) -> ndarray:
        def spectrogram_by_type():
            if type == SpectrogramType.power:
                return self._power_spectrogram()
            if type == SpectrogramType.amplitude:
                return self._amplitude_spectrogram()
            if type == SpectrogramType.power_level:
                return self._power_level_from_power_spectrogram(self._power_spectrogram())

            raise ValueError(type)

        s = spectrogram_by_type()

        return self._convert_spectrogram_to_mel_scale(s) if frequency_scale == SpectrogramFrequencyScale.mel else s

    def z_normalized_transposed_spectrogram(self):
        """
        :return: Array with shape (time, frequencies)
        """
        return z_normalize(self.spectrogram(frequency_scale=SpectrogramFrequencyScale.mel).T)

    @staticmethod
    def frequency_count(spectrogram: ndarray) -> int:
        return spectrogram.shape[0]

    def time_step_count(self) -> int:
        return self.spectrogram().shape[1]

    def time_step_rate(self) -> float:
        return self.time_step_count() / self.duration_in_s()

    def prepare_spectrogram_plot(self, type: SpectrogramType = SpectrogramType.power_level,
                                 frequency_scale: SpectrogramFrequencyScale = SpectrogramFrequencyScale.linear) -> None:
        spectrogram = self.spectrogram(type, frequency_scale=frequency_scale)

        figure, axes = plt.subplots(1, 1)
        use_mel = frequency_scale == SpectrogramFrequencyScale.mel

        plt.title("\n".join(wrap(
            "{0}{1} spectrogram for {2}".format(("mel " if use_mel else ""), type.value, str(self)), width=100)))
        plt.xlabel("time (data every {}ms)".format(round(1000 / self.time_step_rate())))
        plt.ylabel("frequency (data evenly distributed on {} scale, {} total)".format(frequency_scale.value,
                                                                                      self.frequency_count(
                                                                                          spectrogram)))
        mel_frequencies = self.mel_frequencies()
        plt.imshow(
            spectrogram, cmap='gist_heat', origin='lower', aspect='auto', extent=
            [0, self.duration_in_s(),
             librosa.hz_to_mel(mel_frequencies[0])[0] if use_mel else 0,
             librosa.hz_to_mel(mel_frequencies[-1])[0] if use_mel else self.highest_detectable_frequency()])

        plt.colorbar(label="{} ({})".format(type.value,
                                            "in{} dB, not aligned to a particular base level".format(
                                                " something similar to" if use_mel else "") if type == SpectrogramType.power_level else "only proportional to physical scale"))

        axes.xaxis.set_major_formatter(ScalarFormatterWithUnit("s"))
        axes.yaxis.set_major_formatter(
            ticker.FuncFormatter(lambda value, pos: "{}mel = {}Hz".format(int(value), int(
                librosa.mel_to_hz(value)[0]))) if use_mel else ScalarFormatterWithUnit("Hz"))
        figure.set_size_inches(19.20, 10.80)

    @staticmethod
    def _power_level_from_power_spectrogram(spectrogram: ndarray) -> ndarray:
        # default value for min_decibel found by experiment (all values except for 0s were above this bound)
        def power_to_decibel(x, min_decibel: float = -150) -> float:
            if x == 0:
                return min_decibel
            l = 10 * math.log10(x)
            return min_decibel if l < min_decibel else l

        return vectorize(power_to_decibel)(spectrogram)

    def reconstructed_audio_from_spectrogram(self) -> ndarray:
        return librosa.istft(self._complex_spectrogram(), win_length=self.fourier_window_length,
                             hop_length=self.hop_length)

    def plot_reconstructed_audio_from_spectrogram(self) -> None:
        self._plot_audio(self.reconstructed_audio_from_spectrogram())

    def save_reconstructed_audio_from_spectrogram(self, target_directory: Path) -> None:
        librosa.output.write_wav(
            str(Path(target_directory,
                     "{}_window{}_hop{}.wav".format(self.id, self.fourier_window_length, self.hop_length))),
            self.reconstructed_audio_from_spectrogram(), sr=self.sample_rate)

    def save_spectrograms_of_all_types(self, target_directory: Path) -> None:
        for type in SpectrogramType:
            for frequency_scale in SpectrogramFrequencyScale:
                self.save_spectrogram(target_directory=target_directory, type=type,
                                      frequency_scale=frequency_scale)

    def __str__(self) -> str:
        return self.id + (": {}".format(self.label) if self.label else "")
