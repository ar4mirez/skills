"""One exception hierarchy per package, rooted at a single base class.

Callers catch ``LinkError`` to handle anything this package raises on purpose, or a
subclass to branch on a specific condition. Programmer errors (``TypeError``, bugs)
are never wrapped, so they still crash loudly.
"""


class LinkError(Exception):
    """Base class for every error this package raises deliberately."""


class InvalidInputError(LinkError, ValueError):
    """Input failed validation. Also a ``ValueError``, so generic callers still work."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


class NotFoundError(LinkError):
    """The requested thing does not exist."""


class ConflictError(LinkError):
    """The write would violate a uniqueness rule."""
