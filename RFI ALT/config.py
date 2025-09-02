from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Settings:
    local_root: Path
    out_xlsx: Path

    @staticmethod
    def from_env() -> "Settings":
        local_root = Path(os.getenv("LOCAL_ROOT", ".")).resolve()
        out_xlsx = Path(os.getenv("OUT_XLSX", "./_results/rfi_catalog.xlsx")).resolve()
        out_xlsx.parent.mkdir(parents=True, exist_ok=True)
        return Settings(local_root=local_root, out_xlsx=out_xlsx)