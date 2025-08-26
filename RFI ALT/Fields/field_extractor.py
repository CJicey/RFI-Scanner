# fields/field_extractors.py — header fields, parties, sections, refs,
# robust RFI# from folder, and Title strictly from "RFI #...: <Title>" in the PDF
from __future__ import annotations
import re
from typing import Optional, Tuple

# ---------- Title / RFI number helpers ----------
# Match header like:
#   RFI #913: Storm Pipe & Foundation Wall - Area F Gridline E3
#   RFI 913 - Storm Pipe ...
#   RFI No. 913 — Storm Pipe ...
# Loosened (not anchored to start of line) to survive table extraction.
_RFI_TITLE_LINE = re.compile(
    r"""
    RFI                                  # literal RFI
    (?:\s*(?:No\.?|Number))?             # optional "No." / "Number"
    \s*                                  # spaces
    (?:[#])?                             # optional '#'
    \s*([0-9]{1,6}[A-Za-z]?)             # (1) id
    \s*[:\-–—]\s*                        # separator (: - – —)
    ([^\n\r]+)                           # (2) title (to end of line)
    """,
    re.IGNORECASE | re.VERBOSE
)

def rfi_title_from_text(text: str) -> Optional[str]:
    """Return the title from the 'RFI #...: <Title>' header if present, else None."""
    if not text:
        return None
    m = _RFI_TITLE_LINE.search(text)
    if m:
        title = m.group(2).strip()
        title = re.sub(r"\s{2,}", " ", title)  # normalize internal whitespace
        return title[:200]
    return None

# ---------- RFI number (from names, not PDF text) ----------
def rfi_number_from_folder(name: str) -> str:
    """
    Always return a stable ID like 'RFI-913' from a folder/file name.
    Handles:
      'RFI 913_Storm...' , 'RFI-913 – …', 'RFI#913', 'RFI913', '913 Storm Pipe...'
    Fallback -> 'RFI-UNK'
    """
    s = (name or "").strip()
    m = re.search(r"\bRFI\b[^\w]*([0-9]{1,6}[A-Za-z]?)\b", s, re.IGNORECASE)
    if m:
        return f"RFI-{m.group(1).upper()}"
    m = re.search(r"\b([0-9]{1,6}[A-Za-z]?)\b", s)
    if m:
        return f"RFI-{m.group(1).upper()}"
    m = re.search(r"\bRFI([0-9]{1,6}[A-Za-z]?)\b", s, re.IGNORECASE)
    if m:
        return f"RFI-{m.group(1).upper()}"
    return "RFI-UNK"

def title_from_text(text: str) -> str:
    """
    Very last-resort generic snippet (used only when we explicitly want a body snippet).
    """
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    return t[:100]

# ---------- Sheets / Drawing refs ----------
_DETAIL_REF_RE = re.compile(r"\b(\d{1,2})\s*/\s*([A-Z]{1,2}\d{2,4}[A-Z]?)\b", re.IGNORECASE)
_SHEET_TOKEN_RE = re.compile(r"\b([A-Z]{1,2})[-\s]?(\d{2,4})([A-Z]?)\b")

def _normalize_sheet(prefix: str, number: str, suffix: str) -> str:
    return f"{prefix.upper()}-{number}{suffix.upper()}"

def detail_refs(text: str) -> str | None:
    if not text:
        return None
    out = []
    for m in _DETAIL_REF_RE.finditer(text):
        num, sheet = m.group(1), m.group(2)
        m2 = _SHEET_TOKEN_RE.match(sheet)
        if m2:
            out.append(f"{num}/{_normalize_sheet(m2.group(1), m2.group(2), m2.group(3))}")
        else:
            out.append(f"{num}/{sheet.upper()}")
    if not out:
        return None
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return ", ".join(uniq)

def impacted_sheets(text: str) -> str | None:
    if not text:
        return None
    hits = []
    for m in _SHEET_TOKEN_RE.finditer(text):
        hits.append(_normalize_sheet(m.group(1), m.group(2), m.group(3)))
    if not hits:
        return None
    seen, uniq = set(), []
    for x in hits:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return ", ".join(uniq)

# ---------- Header blocks ----------
_DATE = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})"

def _find_after(label: str, text: str, take_line: bool = False) -> Optional[str]:
    if take_line:
        rx = re.compile(rf"{label}\s*[:\-]?\s*([^\n\r]+)", re.IGNORECASE)
    else:
        rx = re.compile(rf"{label}\s*[:\-]?\s*({_DATE})", re.IGNORECASE)
    m = rx.search(text or "")
    return m.group(1).strip() if m else None

def date_initiated(text: str) -> Optional[str]:
    return _find_after(r"\bDate\s+Initiated\b", text)

def due_date(text: str) -> Optional[str]:
    return _find_after(r"\bDue\s+Date\b", text)

def status(text: str) -> Optional[str]:
    return _find_after(r"\bStatus\b", text, take_line=True)

def hot_flag(text: str) -> Optional[str]:
    m = re.search(r"\bHot\?\s*(Yes|No)\b", text or "", re.IGNORECASE)
    return (m.group(1).title() if m else None)

def cost_impact(text: str) -> Optional[str]:
    return _find_after(r"\bCost\s+Impact\b", text, take_line=True)

def schedule_impact(text: str) -> Optional[str]:
    return _find_after(r"\bSchedule\s+Impact\b", text, take_line=True)

def spec_section(text: str) -> Tuple[Optional[str], Optional[str]]:
    m = re.search(r"\bSpec(?:ification)?\s+Section\s+([0-9]{4,6})(?:\s*[-:]\s*([^\n\r]+))?", text or "", re.IGNORECASE)
    if not m:
        return None, None
    return m.group(1), (m.group(2).strip() if m.group(2) else None)

def drawing_number_field(text: str) -> Optional[str]:
    m = re.search(r"\bDrawing\s+Number\s+([A-Z]{1,2}\d{2,4}[A-Z]?)\b", text or "", re.IGNORECASE)
    return m.group(1).upper() if m else None

# ---------- Parties ----------
def _party_line(which: str, text: str) -> Optional[str]:
    rx = re.compile(rf"^\s*{which}\b[^\n\r]*?\s*[:\-]?\s*([^\n\r]+)$", re.IGNORECASE | re.MULTILINE)
    m = rx.search(text or "")
    if m:
        val = m.group(1).strip()
        val = re.sub(r",\s*Copies To.*", "", val, flags=re.IGNORECASE)
        return re.sub(r"\s{2,}", " ", val)[:160]
    return None

def from_party(text: str) -> Optional[str]:
    return _party_line("from", text)

def to_party(text: str) -> Optional[str]:
    return _party_line("to", text)

# ---------- Question / Response ----------
def _extract_section(text: str, start_labels: list[str], end_labels: list[str]) -> Optional[str]:
    if not text:
        return None
    start = r"|".join(re.escape(s) for s in start_labels)
    end   = r"|".join(re.escape(s) for s in end_labels)
    header = r"^\s*[A-Z][A-Z0-9 /#&\-\(\)]{3,}\s*$"

    rx = re.compile(
        rf"(?is)(?:^|\n)\s*(?:{start})\s*[:\-]?\s*(.+?)(?=(?:{end})\s*[:\-]|{header}|$)",
        re.MULTILINE | re.DOTALL
    )
    m = rx.search(text)
    if not m:
        return None
    content = m.group(1).strip()
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r"\n{2,}", "\n", content)
    return content[:3000]

def question(text: str) -> Optional[str]:
    return _extract_section(
        text,
        start_labels=["QUESTION", "RFI QUESTION", "REQUEST"],
        end_labels=["RESPONSE", "ANSWER", "REPLY", "ATTACHMENTS", "NOTES"]
    )

def response(text: str) -> Optional[str]:
    r = _extract_section(
        text,
        start_labels=["RESPONSE", "ANSWER", "REPLY"],
        end_labels=["END RESPONSE", "NOTES", "ATTACHMENTS", "CLOSURE", "CLOSEOUT", "REFERENCES"]
    )
    if r:
        return r
    # heuristic: confirmation-style response without header
    m = re.search(
        r"(?is)\b(Confirmed;.*?)(?:\n\s*[A-Z][a-z]+\s+[A-Z][a-z]+.*?/.*?\d{1,2}/\d{1,2}/\d{2,4}\s*$|\Z)",
        text or ""
    )
    if m:
        re

