# fields/field_extractors.py
from __future__ import annotations
import re
from typing import Optional

def rfi_number_from_folder(folder_name: str) -> str:
    m = re.search(r"\bRFI\s*[-#:]?\s*([A-Za-z0-9._-]+)", folder_name, re.I)
    return m.group(1) if m else folder_name.strip()

def title_from_text(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"^(?:subject|re)\s*[:\-]\s*(.+)$", text, re.I | re.M)
    if m:
        return m.group(1).strip()
    t = re.sub(r"\s+", " ", text).strip()
    return t[:100]

# ---------- Sheets / Sketch references ----------
_SHEET_PATTERN = re.compile(
    r"""
    (?:
        (?:SHEET\s+)?                        # optional 'Sheet '
        (?:A|S|P|M|E|C|T|AD|AE|AS|SD|SI)     # common discipline prefixes
        [-\s]? \d{1,4} [A-Z]?                # number w/ optional suffix
    )
    |
    (?:SK[-\s]?\d{1,4}[A-Z]?)                # SK-235, SK 235A
    """,
    re.IGNORECASE | re.VERBOSE,
)

def impacted_sheets(text: str) -> str | None:
    if not text:
        return None
    hits = _SHEET_PATTERN.findall(text)
    if not hits:
        return None
    norm = []
    for h in hits:
        s = " ".join(h.split()).upper().replace("SHEET ", "")
        s = s.replace(" ", "").replace("--", "-")
        s = re.sub(r"^([A-Z]{1,2})(\d)", r"\1-\2", s)  # A101 -> A-101
        norm.append(s)
    unique = sorted(set(n for n in norm if len(n) >= 3))
    return ", ".join(unique) if unique else None

# ---------- Dates ----------
_DATE = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})"

def _find_date_after(label: str, text: str) -> Optional[str]:
    rx = re.compile(rf"{label}\s*[:\-]?\s*({_DATE})", re.I)
    m = rx.search(text or "")
    return m.group(1) if m else None

def _first_date(text: str) -> Optional[str]:
    m = re.search(_DATE, text or "", re.I)
    return m.group(0) if m else None

def date_submitted(text: str) -> Optional[str]:
    # priority: "Date Submitted", then "Submitted", then first date seen
    for lbl in (r"date\s+submitted", r"\bsubmitted\b", r"\breceived\b"):
        d = _find_date_after(lbl, text or "")
        if d: return d
    return _first_date(text)

def date_responded(text: str) -> Optional[str]:
    # priority: "Date Responded", "Response Date", "Answered"
    for lbl in (r"date\s+responded", r"(?:response|responded)\s+date", r"\banswered\b", r"\breplied\b"):
        d = _find_date_after(lbl, text or "")
        if d: return d
    # fallback heuristic: if two dates exist, take the second as "responded"
    dates = re.findall(_DATE, text or "", re.I)
    if len(dates) >= 2:
        return dates[1]
    return None

# ---------- Parties ----------
def _party_line(which: str, text: str) -> Optional[str]:
    # Match "From: X", "To - Y", "TO/ATTN: Z"
    rx = re.compile(rf"^\s*{which}\s*(?:/|&)?\s*(?:attn\.)?\s*[:\-]\s*(.+)$", re.I | re.M)
    m = rx.search(text or "")
    if m:
        val = m.group(1).strip()
        val = re.sub(r"\s{2,}", " ", val)
        val = re.sub(r"\s*(?:phone|tel|email).*", "", val, flags=re.I)  # trim trailing contacts
        return val[:120]
    return None

def from_party(text: str) -> Optional[str]:
    return _party_line("from", text)

def to_party(text: str) -> Optional[str]:
    return _party_line("to", text)

# ---------- Question / Response sections ----------
def _extract_section(text: str, start_labels: list[str], end_labels: list[str]) -> Optional[str]:
    if not text:
        return None
    # Build a pattern like: (QUESTION|RFI QUESTION) ... (until next END label or uppercase header)
    start = r"|".join(re.escape(s) for s in start_labels)
    end   = r"|".join(re.escape(s) for s in end_labels)

    # Stop at the next header-ish line or end. Header heuristic: ALLCAPS 3+ chars.
    header = r"^\s*[A-Z][A-Z0-9 /#&\-\(\)]{3,}\s*$"

    rx = re.compile(
        rf"(?is)^\s*(?:{start})\s*[:\-]?\s*(.+?)(?=(?:{end})\s*[:\-]|{header}|$)",
        re.MULTILINE | re.DOTALL
    )
    m = rx.search(text)
    if not m:
        return None
    content = m.group(1).strip()
    # normalize whitespace; keep it concise
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r"\n{2,}", "\n", content)
    return content[:2000]  # cap for Excel sanity

def question(text: str) -> Optional[str]:
    return _extract_section(
        text,
        start_labels=["QUESTION", "RFI QUESTION", "REQUEST"],
        end_labels=["RESPONSE", "ANSWER", "REPLY"]
    )

def response(text: str) -> Optional[str]:
    # Try the typical "Response:" block first
    r = _extract_section(
        text,
        start_labels=["RESPONSE", "ANSWER", "REPLY"],
        end_labels=["END RESPONSE", "NOTES", "ATTACHMENTS", "CLOSURE", "CLOSEOUT", "REFERENCES"]
    )
    if r:
        return r
    # Fallback: capture from 'Response:' to the end if nothing else matches
    m = re.search(r"(?is)^\s*(RESPONSE|ANSWER|REPLY)\s*[:\-]\s*(.+)$", text or "")
    return (m.group(2).strip()[:2000]) if m else None