# coding: utf8

import typing

from .utils import safestr

Variable = typing.TypeVar("Variable")


class DictValueValidatorMixin:
    def validate(self, value: Variable) -> Variable:
        if "__origin__" in self.__dict__:
            if isinstance(value, self.__args__):  # type: ignore
                return value
        raise TypeError(f"{value!r} must in types {self.__args__}")  # type: ignore


class MutableDict(typing.MutableMapping):
    def __init__(self, *args, **kwargs):
        self._data = []
        self.update(*args, **kwargs)

    def __setitem__(self, key, value):
        self._data.append(
            (safestr(key).lower().replace("-", "_"), safestr(value) if isinstance(value, (bytes)) else value)
        )

    def __getitem__(self, key):
        values = []
        key = safestr(key.lower().replace("-", "_"))
        for _key, value in self._data:
            if _key == key:
                values.append(value)
        if values:
            if len(values) == 1:
                return values[0]
            return values
        raise KeyError(repr(key))

    def __delitem__(self, key):
        keys_will_poped = []
        safe_key = safestr(key).lower().replace("-", "_")
        for idx, item in enumerate(self._data):
            if item[0] == safe_key:
                keys_will_poped.append(idx)
        for idx in keys_will_poped[::-1]:
            self._data.pop(idx)

    def __iter__(self):
        return (k for k, v in self._data)

    def __len__(self):
        return len(self._data)

    def __getattr__(self, attr):
        if attr in self._data:
            return self._data[attr]
        return super().__getattr__(attr)

    def __repr__(self):
        return f"<MutableDict {dict(self)!r}>"


class ImmutableDict(typing.Mapping):
    def __init__(self, *args, **kwargs):
        self._data = MutableDict(*args, **kwargs)

    def __getitem__(self, key):
        return self._data[safestr(key.lower())]

    def __iter__(self):
        return self._data.keys().__iter__()

    def __len__(self):
        return len(self._data)

    def __getattr__(self, attr):
        if attr in self._data:
            return self._data[attr]
        return super().__getattr__(attr)

    def __repr__(self):
        return f"<ImmutableDict {dict(self)!r}>"


class Validator(typing.Generic[Variable], DictValueValidatorMixin):
    pass


Form = typing.NewType("Form", ImmutableDict)
Cookies = typing.NewType("Cookies", ImmutableDict)
Headers = typing.NewType("Headers", ImmutableDict)
QueryParams = typing.NewType("QueryParams", MutableDict)

Header = typing.NewType("Header", Validator)
Cookie = typing.NewType("Cookie", Validator)
FormField = typing.NewType("FormField", Validator)
QueryParam = typing.NewType("QueryParam", Validator)
UploadedFile = typing.NewType("UploadedFile", Validator[typing.IO])
