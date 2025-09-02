# fields/field_extractors.py
# Minimal extractors kept in use by workers.py:
#   - rfi_number_from_folder()
#   - detail_refs()
from __future__ import annotations
import re
from typing import Iterable, List

# ----------------------------
# RFI number from folder name
# ----------------------------
# Accepts folder names like:
#   "RFI 913 - Storm Pipe ..."
#   "RFI-913"
#   "RFI_913 LE Response"
#   "RFI913"
# Returns standardized "RFI-913" or "" if not found
_RFI_RXES = [
    re.compile(r"\brfi\b[^\d]{0,3}(\d{1,6})\b", re.IGNORECASE),      # RFI 913 / RFI-913 / RFI_913
    re.compile(r"\brfi#?[^\d]{0,1}(\d{1,6})\b", re.IGNORECASE),       # RFI#913 / RFI# 913
    re.compile(r"\brfi(\d{1,6})\b", re.IGNORECASE),                   # RFI913 (no separator)
]

def rfi_number_from_folder(name: str) -> str:
    """
    Try to parse an RFI number from a folder (or filename) and return 'RFI-<N>'.
    If nothing matches, return ''.
    """
    if not name:
        return ""
    for rx in _RFI_RXES:
        m = rx.search(name)
        if m:
            try:
                n = int(m.group(1))
                return f"RFI-{n}"
            except Exception:
                # fall through to try next regex
                pass
    return ""


# ----------------------------
# Detail references extraction
# ----------------------------
# We pick up common notations such as:
#   - "8/S303", "12/A501"
#   - "Detail 5 on S401", "Detail 3 at A-501"
#   - "SK-235", "SK235"
#
# Returned value is a CSV string: "8/S303, 12/A501, SK-235"
#
# Notes:
# - We normalize sheet IDs by collapsing spaces and dashes (A 501 -> A501, S-303 -> S303).
# - We keep original detail number + normalized sheet, e.g., "8/S303".
# - We dedupe while preserving first-seen order.

# 1) Compact "8/S303" pattern (most common)
RX_DETAIL_SLASH = re.compile(
    r"\b(?P<det>\d{1,2})\s*/\s*(?P<sheet>[A-Z]{1,3}[ -]?\d{1,4}[A-Z]?)\b"
)

# 2) Verbose "Detail 5 on S401" / "Detail 5 at A-501"
RX_DETAIL_ON_SHEET = re.compile(
    r"\b(?:detail|det\.?)\s*(?P<det>\d{1,2})\s*(?:on|at)\s*(?P<sheet>[A-Z]{1,3}[ -]?\d{1,4}[A-Z]?)\b",
    re.IGNORECASE,
)

# 3) SK references "SK-235" / "SK235"
RX_SK = re.compile(r"\bSK[- ]?(?P<num>\d{1,4}[A-Z]?)\b", re.IGNORECASE)

def _norm_sheet(s: str) -> str:
    """
    Normalize sheet identifiers:
      'A-501' -> 'A501', 'S 303' -> 'S303', 's-101a' -> 'S101A'
    """
    s = (s or "").strip().upper()
    s = s.replace(" ", "").replace("-", "")
    return s

def _dedup_preserve(seq: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if not x:
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def detail_refs(text: str) -> str:
    """
    Extract detail/sheet references and SK refs from free text.
    Return a CSV string: '8/S303, 12/A501, SK-235'
    """
    t = text or ""
    found: List[str] = []

    # 1) 8/S303 style
    for m in RX_DETAIL_SLASH.finditer(t):
        det = m.group("det")
        sheet = _norm_sheet(m.group("sheet"))
        found.append(f"{det}/{sheet}")

    # 2) 'Detail 5 on S401' style
    for m in RX_DETAIL_ON_SHEET.finditer(t):
        det = m.group("det")
        sheet = _norm_sheet(m.group("sheet"))
        found.append(f"{det}/{sheet}")

    # 3) SK refs
    for m in RX_SK.finditer(t):
        num = (m.group("num") or "").upper()
        num = num.replace(" ", "")
        # Standardize as SK-###
        if not num.startswith("SK-"):
            val = f"SK-{num}"
        else:
            val = num
        # Ensure single hyphen after SK
        val = "SK-" + val.split("SK-")[-1]
        found.append(val)

    # Dedupe and return CSV
    found = _dedup_preserve(found)
    return ", ".join(found)

