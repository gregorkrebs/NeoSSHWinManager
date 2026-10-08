"""
connection_filter.py – The text filter of the connection list.

A connection matches when every word of the query appears in its name, its
host, its user name or "user@host", ignoring case; "kunde arm" finds
"Kunde X" on armhosting.de. An empty query matches everything.
"""

from __future__ import annotations


def terms(query: str) -> list[str]:
    """The words of *query*, case-folded; none for an empty query."""
    return (query or "").casefold().split()


def matches(conn, query: str) -> bool:
    """True if *conn* (anything with name, host and user) matches *query*."""
    words = terms(query)
    if not words:
        return True
    name, host, user = (str(getattr(conn, f, "") or "").casefold() for f in ("name", "host", "user"))
    fields = (name, host, user, f"{user}@{host}")
    return all(any(word in field for field in fields) for word in words)
