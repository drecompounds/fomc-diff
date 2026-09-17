"""The Unicode dash-variant range shared by meetings.py and sep.py.

The Fed's HTML uses several dash-like characters interchangeably within the
same document, and sometimes within the same sentence: U+2010 HYPHEN, U+2011
NON-BREAKING HYPHEN, U+2012 FIGURE DASH, U+2013 EN DASH, U+2014 EM DASH,
U+2015 HORIZONTAL BAR -- plus the entity-encoded en dash (&#8211;, unescaped
before matching) and the plain ASCII hyphen U+002D.

meetings.py and sep.py each build their own dash character class for their
own regexes. They used to keep two independently hand-maintained copies of
this range, and the copies silently diverged: sep.py's `_PAIR_DASH` omitted
the trailing ASCII hyphen that meetings.py's `_DASH` carries, so `_pair`'s
own docstring example ('2.2-2.4' -> (2.2, 2.4)) was false -- an ASCII-hyphen
pair raised.

Import `UNICODE_DASHES` from here and build the final character class
explicitly at each call site, stating whether the ASCII hyphen is included,
rather than re-typing (and risking re-diverging) the Unicode range itself.
"""
from __future__ import annotations

# U+2010-U+2015 as a regex character-range fragment. Does NOT include the
# ASCII hyphen (U+002D): it sorts BELOW U+2010, so it is never swept in by
# this range. Every current call site needs the ASCII hyphen too (the Fed
# writes plain "-" as often as any Unicode dash variant), so each appends
# "\-" explicitly when building its own class.
UNICODE_DASHES = "‐-―"
