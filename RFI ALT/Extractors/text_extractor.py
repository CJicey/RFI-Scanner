from __future__ import annotations
from pathlib import Path
import pdfplumber

def _norm(s: str) -> str:
    # collapse whitespace for a simple, consistent text
    return " ".join((s or "").split())

def extract_text_simple(pdf_path: Path) -> str:
    """
    Minimal, pdfplumber-only extraction for Part 1.
    Returns normalized text (single-line spacing).
    """
    try:
        parts = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for p in pdf.pages:
                t = p.extract_text() or ""
                if t:
                    parts.append(t)
        return _norm("\n".join(parts))
    except Exception:
        return ""