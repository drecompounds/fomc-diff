"""Shared parse-error hierarchy.

A single base lets callers (e.g. a future backfill driver) distinguish
"this document lacks an expected line" from a genuine bug, by catching
FomcParseError instead of a bare ValueError.
"""
from __future__ import annotations


class FomcParseError(ValueError):
    """Base class for errors raised when expected content is missing from
    a document during parsing."""
