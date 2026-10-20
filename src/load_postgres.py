"""Load clean aforo facts and node locations into PostgreSQL using COPY."""

from __future__ import annotations

import csv
import itertools
import os
from pathlib import Path

import pandas as pd
import psycopg


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "processed" / "aforos_limpios.csv"
NODES_FILE = ROOT / "data" / "metadata" / "nodes.csv"
FACT_COLUMNS = [
    "fecha", "hora", "nodo", "modalidad", "categoria", "conteo",
    "sentido", "acceso", "movimiento", "archivo_fuente",
]
NODE_COLUMNS = [
    "nodo", "longitude", "latitude", "localidad", "upz_referencia", "barrio_referencia",
    "via_principal", "via_secundaria", "lugar", "archivos_coordenada",
    "total_archivos_nodo", "fuente_coordenada",
]


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def write_csv(copy, frame: pd.DataFrame, columns: list[str]) -> None:
    writer = csv.writer(copy, lineterminator="\n")
    for row in frame[columns].itertuples(index=False, name=None):
        writer.writerow(["__NULL_VALUE__" if pd.isna(value) else value for value in row])


def main() -> None:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Configura DATABASE_URL en .env (consulta .env.example).")
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"No existe {DATA_FILE}; ejecuta primero src\\clean_data.py.")

    chunks = pd.read_csv(DATA_FILE, dtype={"nodo": "Int64", "movimiento": "string"}, chunksize=100_000)
    first_chunk = next(chunks, None)
    if first_chunk is None:
        raise ValueError("El CSV procesado no contiene filas para cargar.")
    for column in FACT_COLUMNS:
        if column not in first_chunk:
            raise ValueError(f"El CSV procesado no tiene la columna {column}.")
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aforos (
                    fecha DATE NOT NULL,
                    hora TIME NOT NULL,
                    nodo INTEGER NOT NULL,
                    modalidad TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    conteo NUMERIC NOT NULL,
                    sentido TEXT NOT NULL,
                    acceso TEXT NOT NULL,
                    movimiento TEXT NOT NULL,
                    archivo_fuente TEXT NOT NULL,
                    PRIMARY KEY (fecha, hora, nodo, modalidad, categoria, sentido, acceso, movimiento, archivo_fuente)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS nodos (
                    nodo INTEGER PRIMARY KEY,
                    longitude DOUBLE PRECISION NOT NULL,
                    latitude DOUBLE PRECISION NOT NULL,
                    localidad TEXT,
                    upz_referencia TEXT,
                    barrio_referencia TEXT,
                    via_principal TEXT,
                    via_secundaria TEXT,
                    lugar TEXT,
                    archivos_coordenada INTEGER,
                    total_archivos_nodo INTEGER,
                    fuente_coordenada TEXT
                )
            """)
            cursor.execute("ALTER TABLE nodos ADD COLUMN IF NOT EXISTS barrio_referencia TEXT")
            cursor.execute("CREATE TEMP TABLE stage_aforos (LIKE aforos INCLUDING DEFAULTS) ON COMMIT DROP")
            with cursor.copy(
                "COPY stage_aforos (fecha,hora,nodo,modalidad,categoria,conteo,sentido,acceso,movimiento,archivo_fuente) FROM STDIN WITH (FORMAT CSV, NULL '__NULL_VALUE__')"
            ) as copy:
                for chunk in itertools.chain([first_chunk], chunks):
                    write_csv(copy, chunk, FACT_COLUMNS)
            cursor.execute("""
                INSERT INTO aforos
                SELECT * FROM stage_aforos
                ON CONFLICT DO NOTHING
            """)
            inserted_facts = cursor.rowcount

            if NODES_FILE.exists():
                nodes = pd.read_csv(NODES_FILE)
                # A temporary staging table makes catalog refreshes idempotent.
                cursor.execute("CREATE TEMP TABLE stage_nodos (LIKE nodos INCLUDING DEFAULTS) ON COMMIT DROP")
                with cursor.copy(
                    "COPY stage_nodos (nodo,longitude,latitude,localidad,upz_referencia,barrio_referencia,via_principal,via_secundaria,lugar,archivos_coordenada,total_archivos_nodo,fuente_coordenada) FROM STDIN WITH (FORMAT CSV, NULL '__NULL_VALUE__')"
                ) as copy:
                    write_csv(copy, nodes, NODE_COLUMNS)
                cursor.execute("""
                    INSERT INTO nodos SELECT * FROM stage_nodos
                    ON CONFLICT (nodo) DO UPDATE SET
                        longitude=EXCLUDED.longitude, latitude=EXCLUDED.latitude,
                        localidad=EXCLUDED.localidad, upz_referencia=EXCLUDED.upz_referencia,
                        barrio_referencia=EXCLUDED.barrio_referencia,
                        via_principal=EXCLUDED.via_principal, via_secundaria=EXCLUDED.via_secundaria,
                        lugar=EXCLUDED.lugar, archivos_coordenada=EXCLUDED.archivos_coordenada,
                        total_archivos_nodo=EXCLUDED.total_archivos_nodo,
                        fuente_coordenada=EXCLUDED.fuente_coordenada
                """)
                updated_nodes = cursor.rowcount
            else:
                updated_nodes = 0
    print(f"Filas nuevas agregadas a aforos: {inserted_facts:,}")
    print(f"Nodos insertados/actualizados: {updated_nodes:,}")


if __name__ == "__main__":
    main()
