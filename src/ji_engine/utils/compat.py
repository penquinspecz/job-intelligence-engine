from __future__ import annotations

from typing import Iterable, Iterator, Tuple, TypeVar

T = TypeVar("T")
U = TypeVar("U")


try:
    zip([], [], strict=False)

    def zip_pairs(items: Iterable[T], other: Iterable[U]) -> Iterator[Tuple[T, U]]:
        return zip(items, other, strict=False)

except TypeError:

    def zip_pairs(items: Iterable[T], other: Iterable[U]) -> Iterator[Tuple[T, U]]:
        return zip(items, other)  # noqa: B905


__all__ = ["zip_pairs"]
