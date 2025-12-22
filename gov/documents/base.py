"""Shared utilities for PDF document generation."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_BASE = PROJECT_ROOT / "output"


def ensure_output_dir(subdir: str) -> Path:
    """Ensure an output subdirectory exists and return its path."""
    output_dir = OUTPUT_BASE / subdir
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def create_canvas(output_path: Path) -> canvas.Canvas:
    """Create a reportlab canvas for the given output path."""
    return canvas.Canvas(str(output_path), pagesize=LETTER)


def line_writer(
    pdf_canvas: canvas.Canvas,
    start_y: float | None = None,
    x: float = 40,
    line_height: float = 14,
) -> Callable[[str], None]:
    """Return a helper that draws successive lines at a fixed position."""
    _, height = LETTER
    y = height - 40 if start_y is None else start_y

    def write_line(text: str) -> None:
        nonlocal y
        pdf_canvas.drawString(x, y, text)
        y -= line_height

    return write_line
