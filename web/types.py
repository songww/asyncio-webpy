# coding: utf8

import typing

from .utils import Storage


class QueryParams(Storage):
    def get(self, key, default=None):
        value = super().get(key, default)
        if isinstance(value, list) and len(value) == 1:
            return value[0]
        else:
            return value

    def getlist(self, key, default=None):
        return super().get(key, default)

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if isinstance(value, list) and len(value) == 1:
            return value[0]
        else:
            return value


QueryParam = typing.TypeVar("QueryParam")
