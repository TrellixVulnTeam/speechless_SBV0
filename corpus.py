import multiprocessing
import random
from abc import ABCMeta, abstractmethod
from enum import Enum
from multiprocessing.pool import Pool
from pathlib import Path

from os import makedirs
from typing import List, Iterable, Callable, Tuple, Any

import tools
from labeled_example import LabeledExample, LabeledSpectrogram, CachedLabeledSpectrogram
from tools import group, paginate


class ParsingException(Exception):
    pass


class Phase(Enum):
    training = "training"
    test = "test"


class Corpus:
    __metaclass__ = ABCMeta

    def __init__(self,
                 training_examples: List[LabeledExample],
                 test_examples: List[LabeledExample]):
        self.training_examples = training_examples
        self.test_examples = test_examples
        self.examples = training_examples + test_examples

        duplicate_training_ids = tools.duplicates(e.id for e in training_examples)
        if len(duplicate_training_ids) > 0:
            raise ValueError("Duplicate ids in training examples: {}".format(duplicate_training_ids))

        duplicate_test_ids = tools.duplicates(e.id for e in test_examples)
        if len(duplicate_test_ids) > 0:
            raise ValueError("Duplicate ids in test examples: {}".format(duplicate_test_ids))

        overlapping_ids = tools.duplicates(e.id for e in self.examples)

        if len(overlapping_ids) > 0:
            raise ValueError("Overlapping training and test set: {}".format(overlapping_ids))

    @abstractmethod
    def csv_rows(self) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def summary(self) -> str:
        raise NotImplementedError

    def summarize_to_csv(self, summary_csv_file: Path) -> None:
        import csv
        with summary_csv_file.open('w', encoding='utf8') as csv_summary_file:
            writer = csv.writer(csv_summary_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

            for row in self.csv_rows():
                writer.writerow(row)

    def save(self, corpus_csv_file: Path):
        import csv
        with corpus_csv_file.open('w', encoding='utf8') as opened_csv:
            writer = csv.writer(opened_csv, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

            examples_and_phase = [(e, Phase.training) for e in self.training_examples] + \
                                 [(e, Phase.test) for e in self.test_examples]

            for e, phase in examples_and_phase:
                writer.writerow((e.id, str(e.audio_file), e.label, phase.value))

    @staticmethod
    def load(corpus_csv_file: Path) -> 'Corpus':
        import csv
        with corpus_csv_file.open(encoding='utf8') as opened_csv:
            reader = csv.reader(opened_csv, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

            examples = [(LabeledExample(audio_file=Path(audio_file_path), id=id, label=label), Phase[phase])
                        for id, audio_file_path, label, phase in reader]

            return Corpus(training_examples=[e for e, phase in examples if phase == Phase.training],
                          test_examples=[e for e, phase in examples if phase == Phase.test])


class CombinedCorpus(Corpus):
    def __init__(self, corpora: List[Corpus]):
        self.corpora = corpora
        super().__init__(
            training_examples=[example
                               for corpus in corpora
                               for example in corpus.training_examples],
            test_examples=[example
                           for corpus in corpora
                           for example in corpus.test_examples])

    def csv_rows(self) -> List[str]:
        return [row
                for corpus in self.corpora
                for row in corpus.csv_rows()]

    def summary(self) -> str:
        return "\n\n".join([corpus.summary() for corpus in self.corpora]) + \
               "\n\n {} total, {} training, {} test".format(
                   len(self.examples), len(self.training_examples), len(self.test_examples))


class TrainingTestSplit:
    training_only = lambda examples: (examples, [])
    test_only = lambda examples: ([], examples)

    @staticmethod
    def randomly_grouped_by(key_from_example: Callable[[LabeledExample], Any], training_share: float = .9) -> Callable[
        [List[LabeledExample]], Tuple[List[LabeledExample], List[LabeledExample]]]:
        def split(examples: List[LabeledExample]) -> Tuple[List[LabeledExample], List[LabeledExample]]:
            examples_by_directory = group(examples, key=key_from_example)
            directories = examples_by_directory.keys()

            # split must be the same every time:
            random.seed(42)
            keys = set(random.sample(directories, int(training_share * len(directories))))

            training_examples = [example for example in examples if key_from_example(example) in keys]
            test_examples = [example for example in examples if key_from_example(example) not in keys]

            return training_examples, test_examples

        return split

    @staticmethod
    def randomly(training_share: float = .9) -> Callable[
        [List[LabeledExample]], Tuple[List[LabeledExample], List[LabeledExample]]]:
        return TrainingTestSplit.randomly_grouped_by(lambda e: e.id, training_share=training_share)

    @staticmethod
    def randomly_grouped_by_directory(training_share: float = .9) -> Callable[
        [List[LabeledExample]], Tuple[List[LabeledExample], List[LabeledExample]]]:
        return TrainingTestSplit.randomly_grouped_by(lambda e: e.audio_directory, training_share=training_share)

    @staticmethod
    def overfit(training_example_count: int) -> Callable[
        [List[LabeledExample]], Tuple[List[LabeledExample], List[LabeledExample]]]:
        return lambda examples: (examples[:training_example_count], examples[training_example_count:])

    @staticmethod
    def by_directory(test_directory_name: str = "test") -> Callable[
        [List[LabeledExample]], Tuple[List[LabeledExample], List[LabeledExample]]]:
        def split(examples: List[LabeledExample]) -> Tuple[List[LabeledExample], List[LabeledExample]]:
            training_examples = [example for example in examples if example.audio_directory.name != test_directory_name]
            test_examples = [example for example in examples if example.audio_directory.name == test_directory_name]

            return training_examples, test_examples

        return split


def _cache_spectrogram(labeled_spectrogram: CachedLabeledSpectrogram) -> None:
    labeled_spectrogram.z_normalized_transposed_spectrogram()


class LabeledSpectrogramBatchGenerator:
    def __init__(self, corpus: Corpus, spectrogram_cache_directory: Path, batch_size: int = 64):
        # not Path.mkdir() for compatibility with Python 3.4
        makedirs(str(spectrogram_cache_directory), exist_ok=True)

        self.batch_size = batch_size
        self.spectrogram_cache_directory = spectrogram_cache_directory
        self.labeled_training_spectrograms = [
            CachedLabeledSpectrogram(example, spectrogram_cache_directory=spectrogram_cache_directory)
            for example in corpus.training_examples]

        self.labeled_test_spectrograms = [
            CachedLabeledSpectrogram(example, spectrogram_cache_directory=spectrogram_cache_directory)
            for example in corpus.test_examples]

        self.labeled_spectrograms = self.labeled_training_spectrograms + self.labeled_test_spectrograms

    def preview_batch(self) -> List[LabeledSpectrogram]:
        return self.labeled_spectrograms[:self.batch_size]

    def training_batches(self) -> Iterable[List[LabeledSpectrogram]]:
        while True:
            yield random.sample(self.labeled_training_spectrograms, self.batch_size)

    def test_batches(self) -> Iterable[List[LabeledSpectrogram]]:
        return paginate(self.labeled_test_spectrograms, self.batch_size)

    def fill_cache(self) -> None:
        with Pool(processes=multiprocessing.cpu_count()) as pool:
            total = len(self.labeled_spectrograms)
            to_calculate = [s for s in self.labeled_spectrograms if not s.exists()]

            print("Filling cache with {} spectrograms: {} already cached, {} yet to calculate.".format(
                total, total - len(to_calculate), len(to_calculate)))
            print([str(e.spectrogram_cache_file) for e in to_calculate])
            for index, labeled_spectrogram in enumerate(to_calculate):
                if index == 0:
                    print(labeled_spectrogram.spectrogram_cache_file)
                pool.apply(_cache_spectrogram, (labeled_spectrogram,))

            pool.close()
            pool.join()
