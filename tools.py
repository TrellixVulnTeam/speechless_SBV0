from itertools import groupby
from pathlib import Path
from time import strftime

from collections import OrderedDict, Counter
from os import makedirs, path
from typing import List, Iterable, TypeVar, Callable, Optional, Dict, Tuple

E = TypeVar('Element')


def single(sequence: List[E]) -> E:
    first = sequence[0]

    assert (len(sequence) == 1)

    return first


def single_or_none(sequence: List[E]) -> Optional[E]:
    assert (len(sequence) <= 1)

    return next(iter(sequence), None)


def read_text(path: Path, encoding=None) -> str:
    """
    Not Path.read_text for compatibility with Python 3.4.
    """
    with path.open(encoding=encoding) as f:
        return f.read()


def mkdir(directory: Path) -> None:
    """
    Not Path.mkdir() for compatibility with Python 3.4.
    """
    makedirs(str(directory), exist_ok=True)


def home_directory() -> Path:
    """
    Not Path.home() for compatibility with Python 3.4.
    """
    return Path(path.expanduser('~'))


def name_without_extension(audio_file: Path) -> str:
    return path.splitext(audio_file.name)[0]


def extension(audio_file: Path) -> str:
    return path.splitext(audio_file.name)[1]


def distinct(sequence: List[E]) -> List[E]:
    return list(OrderedDict.fromkeys(sequence))


def count_summary(sequence: List[E]) -> str:
    return ", ".join(["{}: {}".format(tag, count) for tag, count in Counter(sequence).most_common()])


K = TypeVar('Key')
V = TypeVar('Value')


def group(iterable: Iterable[E], key: Callable[[E], K], value: Callable[[E], V] = lambda x: x) -> Dict[K, Tuple[V]]:
    return OrderedDict((k, tuple(map(value, values))) for k, values in groupby(sorted(iterable, key=key), key))


def timestamp() -> str:
    return strftime("%Y%m%d-%H%M%S")


def duplicates(sequence: Iterable[E]) -> List[E]:
    return [item for item, count in Counter(sequence).items() if count > 1]


def average(numbers: List[float]) -> float:
    return sum(numbers) / len(numbers)


def paginate(sequence: List[E], page_size: int) -> Iterable[List[E]]:
    for start in range(0, len(sequence), page_size):
        yield sequence[start:start + page_size]
