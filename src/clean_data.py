"""Normalize official Bogotá mobility count workbooks into one CSV."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_FILE = PROCESSED_DIR / "aforos_limpios.csv"

ID_COLUMNS = ["NODO", "FECHA", "PERIODO", "SENTIDO", "ACCESO", "MOVIMIENTO"]
VEHICLE_CLASSES = {
    "M": "motos",
    "L": "livianos",
    "B": "buses",
    "TAXI": "taxi",
    "CAM_PEQUEÑO": "camiones_pequeños",
    "CAM_GRANDE": "camiones_grandes",
    "C2": "C2",
    "C3": "C3",
    "C4": "C4",
    ">=C4": ">=C4",
    "AT": "AT",
    "INT": "INT",
}
BIKE_CLASSES = {
    "BI": "bicicletas",
    "BI_CALZADA": "bicicletas_calzada",
    "BICI_CICLORUTA": "bicicletas_ciclorruta",
    "BICI_BICICARRIL": "bicicletas_bicicarril",
    "BI-CEBRA": "bicicletas_cruce_cebra",
}


def study_date_from_identification(path: Path) -> pd.Timestamp | None:
    """Read the declared study date, which can correct malformed FECHA cells."""
    try:
        identification = pd.read_excel(path, sheet_name="Identificacion", header=None)
    except Exception:
        return None
    for row in identification.itertuples(index=False, name=None):
        values = [value for value in row if pd.notna(value)]
        for index, value in enumerate(values[:-1]):
            label = str(value).strip().upper()
            if label.startswith("FECHAS DEL ESTUDIO"):
                date = pd.to_datetime(values[index + 1], errors="coerce")
                return None if pd.isna(date) else date.normalize()
    return None


def normalize_workbook(path: Path) -> pd.DataFrame:
    try:
        data = pd.read_excel(path, sheet_name="vol-data")
    except (ValueError, KeyError) as error:
        print(f"Omitido {path.name}: no tiene hoja vol-data ({error})")
        return pd.DataFrame()
    data.columns = [str(column).strip().upper() for column in data.columns]
    data.columns = [column.replace("CAM_PEQUENO", "CAM_PEQUEÑO") for column in data.columns]

    missing_id = [column for column in ID_COLUMNS if column not in data.columns]
    if missing_id:
        raise ValueError(f"{path.name}: faltan columnas de identificación: {missing_id}")

    bike_classes = [column for column in BIKE_CLASSES if column in data.columns]
    vehicle_classes = [column for column in VEHICLE_CLASSES if column in data.columns]
    datasets = []

    if bike_classes:
        bikes = data[ID_COLUMNS + bike_classes].melt(
            id_vars=ID_COLUMNS,
            value_vars=bike_classes,
            var_name="codigo_categoria",
            value_name="conteo",
        )
        bikes["modalidad"] = "bicicleta"
        bikes["categoria"] = bikes["codigo_categoria"].map(BIKE_CLASSES)
        datasets.append(bikes.drop(columns="codigo_categoria"))

    if vehicle_classes:
        vehicles = data[ID_COLUMNS + vehicle_classes].melt(
            id_vars=ID_COLUMNS,
            value_vars=vehicle_classes,
            var_name="codigo_categoria",
            value_name="conteo",
        )
        vehicles["modalidad"] = "vehiculo"
        vehicles["categoria"] = vehicles["codigo_categoria"].map(VEHICLE_CLASSES)
        datasets.append(vehicles.drop(columns="codigo_categoria"))

    if not datasets:
        print(f"Omitido {path.name}: no tiene categorías de bicicletas o vehículos reconocidas.")
        return pd.DataFrame()

    long_data = pd.concat(datasets, ignore_index=True)

    dates = pd.to_datetime(long_data["FECHA"], errors="coerce").dt.normalize()
    declared_date = study_date_from_identification(path)
    current_date = pd.Timestamp.now().normalize()
    if dates.dropna().nunique() == 1 and declared_date is not None:
        observed_date = dates.dropna().iloc[0]
        if observed_date > current_date and declared_date <= current_date:
            print(
                f"Fecha futura corregida en {path.name}: FECHA={observed_date:%Y-%m-%d}, "
                f"Identificacion={declared_date:%Y-%m-%d}."
            )
            dates = pd.Series(declared_date, index=dates.index)
    long_data["fecha"] = dates.dt.strftime("%Y-%m-%d")
    period_digits = (
        long_data["PERIODO"].astype("string").str.replace(r"\D", "", regex=True).str.zfill(4)
    )
    long_data["hora"] = pd.to_datetime(period_digits, format="%H%M", errors="coerce").dt.strftime("%H:%M")
    long_data["conteo"] = pd.to_numeric(long_data["conteo"], errors="coerce")
    long_data["nodo"] = pd.to_numeric(long_data["NODO"], errors="coerce").astype("Int64")
    long_data["sentido"] = long_data["SENTIDO"].astype("string").str.strip()
    long_data["acceso"] = long_data["ACCESO"].astype("string").str.strip()
    long_data["movimiento"] = long_data["MOVIMIENTO"].astype("string").str.strip()
    long_data["archivo_fuente"] = path.name

    result = long_data[
        [
            "fecha",
            "hora",
            "nodo",
            "modalidad",
            "categoria",
            "conteo",
            "sentido",
            "acceso",
            "movimiento",
            "archivo_fuente",
        ]
    ].copy()
    missing_counts = int(result["conteo"].isna().sum())
    if missing_counts:
        print(f"Filas omitidas por conteo vacío en {path.name}: {missing_counts}")
    result = result.dropna(subset=["conteo"])
    return result


def main() -> None:
    files = sorted(RAW_DIR.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"No encontré archivos .xlsx en {RAW_DIR}")

    frames = [normalize_workbook(path) for path in files]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise ValueError("No encontré hojas con categorías compatibles de bicicletas o vehículos.")
    cleaned = pd.concat(frames, ignore_index=True)
    invalid = cleaned[cleaned["hora"].isna() | cleaned["fecha"].isna()]
    if not invalid.empty:
        raise ValueError(f"Hay {len(invalid)} filas con fecha u hora no reconocida; revisa los archivos fuente.")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print(f"Excel analizados: {len(files)}")
    print(f"Excel con categorías compatibles: {len(frames)}")
    print(f"Filas limpias: {len(cleaned)}")
    print(f"Fuentes: {cleaned['archivo_fuente'].nunique()}")
    print(f"Fechas: {', '.join(sorted(cleaned['fecha'].dropna().unique()))}")
    print(f"Archivo generado: {OUTPUT_FILE}")
    print("Filas por modalidad y categoría:")
    print(cleaned.groupby(["modalidad", "categoria"], dropna=False).size().to_string())


if __name__ == "__main__":
    main()
