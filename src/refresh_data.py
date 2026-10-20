"""Run the complete local refresh: ZIP ingestion, clean, summaries and location catalog."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def has_database_url() -> bool:
    if os.getenv("DATABASE_URL"):
        return True
    env_file = ROOT / ".env"
    return env_file.exists() and any(
        line.strip().startswith("DATABASE_URL=") and line.split("=", 1)[1].strip()
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )


def run(script: str) -> None:
    print(f"\n--- {script} ---", flush=True)
    subprocess.run([sys.executable, str(ROOT / "src" / script)], cwd=ROOT, check=True)


def main() -> None:
    for name in ("localidades.geojson", "upz.geojson", "barrios.geojson"):
        if not (ROOT / "data" / "reference" / name).exists():
            run("download_geo_reference.py")
            break
    for script in (
        "ingest_zip.py", "clean_data.py", "analyze_data.py", "build_node_catalog.py", "publish_dataset.py"
    ):
        run(script)
    if has_database_url():
        run("load_postgres.py")
    else:
        print("PostgreSQL omitido: DATABASE_URL no está configurada. Los CSV locales sí fueron actualizados.")


if __name__ == "__main__":
    main()
