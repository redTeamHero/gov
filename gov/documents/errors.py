"""Errors for document generation."""


class PDFGenerationError(RuntimeError):
    """Raised when PDF generation fails due to schema or filesystem errors."""
