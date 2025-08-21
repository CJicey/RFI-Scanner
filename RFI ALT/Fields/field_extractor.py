from __future__ import annotations
import re

def rfi_number_from_folder(folder_name: str) -> str:
    """
    Examples:
      'RFI 001 - Slab Edge' -> '001'
      'RFI-205 Window Head' -> '205'
      '123' -> '123'  (fallback: return name)
    """
    m = re.search(r"\bRFI\s*[-#:]?\s*([A-Za-z0-9._-]+)", folder_name, re.I)
    return m.group(1) if m else folder_name.strip()

def title_from_text(text: str) -> str:
    """
    Minimal heuristic for Part 1:
      - Try 'Subject:' or 'RE:' lines
      - Fallback: first ~100 chars of the text
    """
    if not text:
        return ""
    m = re.search(r"^(?:subject|re)\s*[:\-]\s*(.+)$", text, re.I | re.M)
    if m:
        return m.group(1).strip()
    # fallback: first sentence-ish chunk
    t = re.sub(r"\s+", " ", text).strip()
    return t[:100]