"""Utilities for make the code run both on Python2 and Python3.
"""

from urllib.parse import urljoin

# Dictionary iteration
iterkeys = lambda d: iter(d.keys())
itervalues = lambda d: iter(d.values())
iteritems = lambda d: iter(d.items())

# string and text types
text_type = str
string_types = (str,)
numeric_types = (int,)

is_iter = lambda x: x and hasattr(x, "__next__")
