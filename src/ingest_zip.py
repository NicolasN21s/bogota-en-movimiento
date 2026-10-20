"""Extract official aforo workbooks from ZIPs and register study metadata."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INCOMING_DIR = ROOT / "data" / "incoming"
RAW_DIR = ROOT / "data" / "raw"
METADATA_FILE = ROOT / "data" / "metadata" / "studies.csv"
SUPPORTED_EXTENSIONS = {".xlsx"}
METADATA_COLUMNS = [
    "archivo_fuente",
    "fecha",
    "modalidad",
    "franjas_esperadas",
    "intervalo_minutos",
    "codigos_movimiento_esperados",
    "nodo",
]
TIME_RANGE_PATTERN = re.compile(
    r"(\d{1,2}:\d{2})(?::\d{2})?\s*(?:A|HASTA|[-–])\s*(\d{1,2}:\d{2})(?::\d{2})?",
    re.IGNORECASE,
)
# The area ZIP contains many study types. Keep only vehicle and bicycle volume
# studies; names such as VOLP (pedestrians) and VD (speed/direction) are excluded.
VOLUME_STUDY_PATTERN = re.compile(r"_(VOLB?|VOL)(?=$|[_ ({}.])", re.IGNORECASE)


def sha256_stream(stream) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream)[0]


def is_volume_study(filename: str) -> bool:
    stem = Path(filename).stem.upper().rstrip(" }.")
    return bool(VOLUME_STUDY_PATTERN.search(stem))


def safe_extract_workbooks(zip_path: Path, known_hashes: dict[str, Path]) -> tuple[int, int, list[str]]:
    extracted = skipped = 0
    messages: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = Path(member.filename.replace("\\", "/")).name
            suffix = Path(name).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS or name.startswith("~$"):
                if suffix in {".xls", ".xlsm"}:
                    messages.append(f"Formato omitido (esta versión procesa .xlsx): {name}")
                skipped += 1
                continue

            if not is_volume_study(name):
                skipped += 1
                continue

            with archive.open(member) as source:
                digest, size = sha256_stream(source)
            if digest in known_hashes:
                skipped += 1
                messages.append(f"Duplicado omitido: {name} (ya está como {known_hashes[digest].name})")
                continue

            destination = RAW_DIR / name
            if destination.exists():
                destination = RAW_DIR / f"{Path(name).stem}__{digest[:8]}{suffix}"
                if destination.exists():
                    skipped += 1
                    continue

            with archive.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
            extracted += 1
            known_hashes[digest] = destination
            messages.append(f"Extraído: {destination.name} ({size:,} bytes)")
    return extracted, skipped, messages


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().upper()


def nonempty_rows(frame: pd.DataFrame) -> list[list[str]]:
    result = []
    for _, row in frame.iterrows():
        values = [clean_text(value) for value in row.tolist()]
        values = [value for value in values if value]
        if values:
            result.append(values)
    return result


def find_labeled_value(rows: list[list[str]], label: str) -> str:
    target = normalized(label)
    for values in rows:
        for index, value in enumerate(values[:-1]):
            if normalized(value).startswith(target):
                return values[index + 1]
    return ""


def read_study_metadata(path: Path) -> list[dict[str, str]]:
    try:
        identification = pd.read_excel(path, sheet_name="Identificacion", header=None)
        volume_columns = pd.read_excel(path, sheet_name="vol-data", nrows=0).columns
    except Exception as error:
        print(f"No pude leer {path.name}: {error}")
        return []

    rows = nonempty_rows(identification)
    date_text = find_labeled_value(rows, "FECHAS DEL ESTUDIO")
    node = find_labeled_value(rows, "NODO NUMERO")
    declared_date = pd.to_datetime(date_text, errors="coerce")
    try:
        volume_date = pd.to_datetime(
            pd.read_excel(path, sheet_name="vol-data", usecols=["FECHA"], nrows=1).iloc[0, 0],
            errors="coerce",
        )
    except Exception:
        volume_date = pd.NaT
    current_date = pd.Timestamp.now().normalize()
    study_date = volume_date
    if pd.isna(study_date) or (study_date.normalize() > current_date and not pd.isna(declared_date) and declared_date.normalize() <= current_date):
        study_date = declared_date
    if pd.isna(study_date):
        print(f"No encontré la fecha del estudio en {path.name}; conservaré su registro previo si existe.")
        return []

    normalized_columns = {normalized(column) for column in volume_columns}
    has_bikes = bool(normalized_columns & {"BI", "BI_CALZADA", "BICI_CICLORUTA", "BICI_BICICARRIL", "BI-CEBRA"})
    has_bikes = has_bikes or any(
        column.startswith(("BI_", "BI-", "BICI_")) for column in normalized_columns
    )
    has_vehicles = bool(normalized_columns & {
        "M", "L", "B", "TAXI", "CAM_PEQUENO", "CAM_GRANDE", "C2", "C3", "C4", ">=C4", "AT", "INT"
    })
    modalities = (["bicicleta"] if has_bikes else []) + (["vehiculo"] if has_vehicles else [])
    if not modalities:
        print(f"Estudio omitido (sin columnas de bicicleta/vehículo reconocidas): {path.name}")
        return []
    in_schedule_section = False
    in_movement_section = False
    ranges: list[str] = []
    movement_codes: list[str] = []

    for values in rows:
        joined = " | ".join(normalized(value) for value in values)
        if "FRANJAS HORARIAS DEL ESTUDIO" in joined:
            in_schedule_section = True
            in_movement_section = False
            continue
        if "MOVIMIENTOS DEL ESTUDIO" in joined:
            in_schedule_section = False
            in_movement_section = True
            continue
        if any(section in joined for section in [
            "TIPOS DE VEHICULO DEL ESTUDIO",
            "OBSERVACIONES PREVIAS",
            "RESPONSABLES DEL ESTUDIO",
        ]):
            in_schedule_section = False
            in_movement_section = False

        if in_schedule_section:
            for value in values:
                for start, end in TIME_RANGE_PATTERN.findall(value):
                    start_hour, start_minute = start.split(":", maxsplit=1)
                    end_hour, end_minute = end.split(":", maxsplit=1)
                    start = f"{int(start_hour):02d}:{start_minute[:2]}"
                    end = f"{int(end_hour):02d}:{end_minute[:2]}"
                    time_range = f"{start}-{end}"
                    if time_range not in ranges:
                        ranges.append(time_range)

        if in_movement_section and "CODIGO DEL MOVIMIENTO" not in joined and len(values) >= 2:
            code = values[1]
            if re.fullmatch(r"\d+(?:\.0)?", code):
                code = str(int(float(code)))
                if code not in movement_codes:
                    movement_codes.append(code)

    if not ranges or not movement_codes:
        print(
            f"Ficha incompleta en {path.name}: "
            f"franjas={ranges or 'no encontradas'}, movimientos={movement_codes or 'no encontrados'}."
        )
        return []

    return [
        {
            "archivo_fuente": path.name,
            "fecha": study_date.strftime("%Y-%m-%d"),
            "modalidad": modality,
            "franjas_esperadas": "|".join(ranges),
            "intervalo_minutos": "15",
            "codigos_movimiento_esperados": "|".join(movement_codes),
            "nodo": node,
        }
        for modality in modalities
    ]


def update_study_registry() -> tuple[int, int]:
    if METADATA_FILE.exists():
        existing = pd.read_csv(METADATA_FILE, dtype=str).fillna("")
    else:
        existing = pd.DataFrame(columns=METADATA_COLUMNS)
    for column in METADATA_COLUMNS:
        if column not in existing:
            existing[column] = ""
    registry = {
        (row["archivo_fuente"], row["modalidad"]): row
        for row in existing.to_dict("records")
    }

    parsed_count = 0
    for path in sorted(RAW_DIR.glob("*.xlsx")):
        metadata_rows = read_study_metadata(path)
        if metadata_rows:
            for metadata in metadata_rows:
                registry[(path.name, metadata["modalidad"])] = metadata
            parsed_count += 1

    result = pd.DataFrame(registry.values(), columns=METADATA_COLUMNS)
    if not result.empty:
        result = result.sort_values(["fecha", "archivo_fuente"])
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(METADATA_FILE, index=False, encoding="utf-8-sig")
    return parsed_count, len(result)


def main() -> None:
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    archives = sorted(INCOMING_DIR.glob("*.zip"))
    if not archives:
        print(f"No hay ZIP en {INCOMING_DIR}; actualizaré la ficha de los Excel que ya están en data/raw.")

    total_extracted = total_skipped = 0
    has_unsupported = False
    known_hashes = {file_sha256(path): path for path in RAW_DIR.glob("*.xlsx")}
    print("Se importarán únicamente Excel de aforos VOL/VOLB; se omiten peatones, velocidad y otros estudios.")
    for archive_path in archives:
        print(f"\nLeyendo ZIP: {archive_path.name}")
        extracted, skipped, messages = safe_extract_workbooks(archive_path, known_hashes)
        total_extracted += extracted
        total_skipped += skipped
        for message in messages:
            print(message)
            has_unsupported |= message.startswith("Formato omitido")

    parsed, registered = update_study_registry()
    print(f"\nExcel nuevos extraídos: {total_extracted}")
    print(f"Elementos omitidos o ya existentes: {total_skipped}")
    print(f"Fichas leídas de Identificacion: {parsed}")
    print(f"Estudios registrados: {registered}")
    print(f"Registro actualizado: {METADATA_FILE}")
    if has_unsupported:
        print("Hay formatos no .xlsx omitidos; será necesario ampliar el lector para procesarlos.")
    print("Los ZIP originales se conservan en data/incoming.")


if __name__ == "__main__":
    main()
