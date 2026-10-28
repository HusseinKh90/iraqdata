"""
Errors and warnings raised by the iraqdata client.

Each error also subclasses the built-in type raised for the same situation before, so existing
`except FileNotFoundError` / `except ValueError` clauses keep working.
"""

from __future__ import annotations


class IraqdataError(Exception):
    """Base class of the errors raised by iraqdata."""


class RepositoryNotFoundError(IraqdataError, FileNotFoundError):
    """The release repository (IRAQDATA_REPO) does not exist."""


class ReleaseNotFoundError(IraqdataError, FileNotFoundError):
    """The requested data release does not exist in the repository."""


class FileNotInReleaseError(IraqdataError, FileNotFoundError):
    """The release exists but does not publish the requested file."""


class ChecksumMismatchError(IraqdataError, ValueError):
    """A downloaded file does not match the checksum its release publishes."""


class UnverifiableFileError(IraqdataError, ValueError):
    """A file cannot be verified: the release has no usable checksum entry for it."""


class NoVintageHistoryError(IraqdataError, LookupError):
    """An as-of request was made on a data source that carries no vintage history."""


class FlagWarning(UserWarning):
    """A wide result contains break (B) or provisional (P) values that its columns do not show."""
