"""Shared entry error type without importing workflow or execution owners."""

class LocalEntryError(RuntimeError):
    """Raised when the active local product entry cannot proceed."""

