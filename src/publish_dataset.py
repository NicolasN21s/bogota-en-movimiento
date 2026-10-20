"""Create the compressed, non-sensitive public snapshot used by cloud deployment."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "processed" / "aforos_limpios.csv"
TARGET = ROOT / "data" / "public" / "aforos_limpios.csv.gz"


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(f"No existe {SOURCE}; ejecuta primero src\\clean_data.py.")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with SOURCE.open("rb") as source, gzip.open(TARGET, "wb", compresslevel=6) as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    print(f"Snapshot público: {TARGET} ({TARGET.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
