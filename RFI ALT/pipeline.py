# pipeline.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Tuple
import os
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed

from Fields.field_extractor import rfi_number_from_folder
from workers import process_pdf

Row = Dict[str, Any]
Audit = Dict[str, Any]

EXCLUDE_DIRS = {
    "__pycache__", "_results", "extractors", "fields", "nlp",
    ".git", ".github", ".venv", "venv", "env",
    "node_modules", ".idea", ".vscode", ".pytest_cache"
}

def _discover_tasks(local_root: Path) -> List[Tuple[str, str]]:
    tasks: List[Tuple[str, str]] = []
    if not local_root.exists():
        raise FileNotFoundError(f"LOCAL_ROOT not found: {local_root}")

    subdirs = sorted(
        p for p in local_root.iterdir()
        if p.is_dir()
        and p.name not in EXCLUDE_DIRS
        and not p.name.startswith((".", "_"))
    )

    if subdirs:
        for rfi_dir in subdirs:
            pdfs = sorted(rfi_dir.rglob("*.pdf"))
            if not pdfs:
                continue
            rfi_no = rfi_number_from_folder(rfi_dir.name)
            for pdf in pdfs:
                tasks.append((str(pdf), rfi_no))
    else:
        for pdf in sorted(local_root.glob("*.pdf")):
            rfi_no = rfi_number_from_folder(pdf.stem)
            tasks.append((str(pdf), rfi_no))

    return tasks

def run_local(
    local_root: Path,
    limit: int | None = None,
    ocr_if_needed: bool = True,
    ocr_max_pages: int = 10,
    workers: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (results_df, audit_df)
    """
    all_tasks = _discover_tasks(local_root)
    if not all_tasks:
        print(f"⚠️ No PDFs found under {local_root}.")
        return pd.DataFrame([]), pd.DataFrame([])

    if limit:
        all_tasks = all_tasks[:limit]

    if workers in (None, 0):
        cpu = os.cpu_count() or 2
        workers = max(1, cpu - 1)

    rows: List[Row] = []
    audit: List[Audit] = []

    if workers == 1:
        for pdf_path, rfi_no in tqdm(all_tasks, desc="Processing PDFs"):
            result = process_pdf(pdf_path, rfi_no, ocr_if_needed, ocr_max_pages)
            rows.append(result["row"])
            audit.append(result["meta"])
        return pd.DataFrame(rows), pd.DataFrame(audit)

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [
            ex.submit(process_pdf, pdf_path, rfi_no, ocr_if_needed, ocr_max_pages)
            for (pdf_path, rfi_no) in all_tasks
        ]
        for fut in tqdm(as_completed(futures), total=len(futures), desc=f"Processing with {workers} workers"):
            result = fut.result()
            rows.append(result["row"])
            audit.append(result["meta"])

    return pd.DataFrame(rows), pd.DataFrame(audit)