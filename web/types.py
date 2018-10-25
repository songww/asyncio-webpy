# coding: utf8

import typing


class QueryParams(dict):
    def get(self, key, default=None):
        value = super().get(key, default)
        if isinstance(value, (list, tuple)):
            return value[0]
        else:
            return value

    def getlist(self, key, default=None):
        return super().get(key, default)


QueryParam = typing.TypeVar("QueryParam")
