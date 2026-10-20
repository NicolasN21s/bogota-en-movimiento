"""Build a node location catalog from workbook metadata and official boundary layers."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
REFERENCE_DIR = ROOT / "data" / "reference"
OUTPUT = ROOT / "data" / "metadata" / "nodes.csv"
CLEAN_DATA = ROOT / "data" / "processed" / "aforos_limpios.csv"
COORDINATE_RE = re.compile(r"\(?\s*(-?\d+(?:\.\d+)?)\s*[,;]\s*(-?\d+(?:\.\d+)?)\s*\)?")


def clean(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def identify_rows(path: Path) -> dict[str, str] | None:
    try:
        frame = pd.read_excel(path, sheet_name="Identificacion", header=None)
    except Exception:
        return None
    labels = {
        "nodo": "NODO NUMERO",
        "lugar": "LUGAR DE LA TOMA DE INFORMACION",
        "via_principal": "VIA PRINCIPAL",
        "via_secundaria": "VIA SECUNDARIA",
        "coordenadas": "COORDENADAS DEL ESTUDIO",
    }
    result: dict[str, str] = {}
    for row in frame.itertuples(index=False, name=None):
        cells = [clean(value) for value in row if clean(value)]
        for i, cell in enumerate(cells[:-1]):
            normalized = cell.upper().replace("Ó", "O").replace("Í", "I").replace("Ú", "U").replace("É", "E").replace("Á", "A")
            for key, label in labels.items():
                if normalized.startswith(label) and cells[i + 1]:
                    result.setdefault(key, cells[i + 1])
    match = COORDINATE_RE.search(result.get("coordenadas", ""))
    if not match:
        return None
    longitude, latitude = float(match.group(1)), float(match.group(2))
    if not (-75 <= longitude <= -73 and 3 <= latitude <= 6):
        return None
    result["longitude"] = str(longitude)
    result["latitude"] = str(latitude)
    result["archivo_fuente"] = path.name
    return result if result.get("nodo") else None


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i, (xi, yi, *_) in enumerate(ring):
        xj, yj, *_ = ring[j]
        if (yi > lat) != (yj > lat):
            cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < cross:
                inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    return bool(rings and point_in_ring(lon, lat, rings[0]) and not any(point_in_ring(lon, lat, hole) for hole in rings[1:]))


def point_in_geometry(lon: float, lat: float, geometry: dict) -> bool:
    if geometry["type"] == "Polygon":
        return point_in_polygon(lon, lat, geometry["coordinates"])
    if geometry["type"] == "MultiPolygon":
        return any(point_in_polygon(lon, lat, polygon) for polygon in geometry["coordinates"])
    return False


def feature_name(feature: dict, candidates: tuple[str, ...]) -> str:
    props = feature.get("properties", {})
    return next((str(props[key]).strip() for key in candidates if props.get(key)), "")


def geometry_bounds(geometry: dict) -> tuple[float, float, float, float]:
    points = []
    stack = [geometry.get("coordinates", [])]
    while stack:
        item = stack.pop()
        if not isinstance(item, list):
            continue
        if item and isinstance(item[0], (int, float)):
            points.append(item)
        else:
            stack.extend(item)
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def prepare_features(features: list[dict]) -> list[tuple[dict, tuple[float, float, float, float]]]:
    return [
        (feature, geometry_bounds(feature["geometry"]))
        for feature in features
        if feature.get("geometry")
    ]


def lookup(
    lon: float,
    lat: float,
    features: list[tuple[dict, tuple[float, float, float, float]]],
    candidates: tuple[str, ...],
) -> str:
    for feature, bounds in features:
        geometry = feature.get("geometry")
        if bounds[0] <= lon <= bounds[2] and bounds[1] <= lat <= bounds[3] and point_in_geometry(lon, lat, geometry):
            return feature_name(feature, candidates)
    return ""


def main() -> None:
    if not CLEAN_DATA.exists():
        raise FileNotFoundError(f"No existe {CLEAN_DATA}; ejecuta primero src\\clean_data.py.")
    locality_file, upz_file = REFERENCE_DIR / "localidades.geojson", REFERENCE_DIR / "upz.geojson"
    if not locality_file.exists() or not upz_file.exists():
        raise FileNotFoundError("Faltan capas oficiales. Ejecuta primero python src\\download_geo_reference.py")
    localities = prepare_features(json.loads(locality_file.read_text(encoding="utf-8"))["features"])
    upzs = prepare_features(json.loads(upz_file.read_text(encoding="utf-8"))["features"])
    neighborhoods_file = REFERENCE_DIR / "barrios.geojson"
    neighborhoods = prepare_features(json.loads(neighborhoods_file.read_text(encoding="utf-8"))["features"]) if neighborhoods_file.exists() else []

    data_nodes = set(pd.read_csv(CLEAN_DATA, usecols=["nodo"])["nodo"].dropna().astype(int))
    observed = [item for path in sorted(RAW_DIR.glob("*.xlsx")) if (item := identify_rows(path))]
    by_node: dict[int, list[dict[str, str]]] = {}
    for item in observed:
        try:
            node = int(float(item["nodo"]))
            if node in data_nodes:
                by_node.setdefault(node, []).append(item)
        except ValueError:
            continue

    rows = []
    for node, candidates in sorted(by_node.items()):
        coord_counts = Counter((item["longitude"], item["latitude"]) for item in candidates)
        (lon_text, lat_text), coord_frequency = coord_counts.most_common(1)[0]
        matching = [item for item in candidates if (item["longitude"], item["latitude"]) == (lon_text, lat_text)]
        best = Counter(item.get("lugar", "") for item in matching if item.get("lugar")).most_common(1)
        main_road = Counter(item.get("via_principal", "") for item in matching if item.get("via_principal")).most_common(1)
        secondary_road = Counter(item.get("via_secundaria", "") for item in matching if item.get("via_secundaria")).most_common(1)
        lon, lat = float(lon_text), float(lat_text)
        rows.append({
            "nodo": node,
            "longitude": lon,
            "latitude": lat,
            "localidad": lookup(lon, lat, localities, ("LOCNOMBRE", "NOMBRE", "NOM_LOCALIDAD")),
            "upz_referencia": lookup(lon, lat, upzs, ("NOMBRE", "NOMBRE_UPZ", "UPZ")),
            "barrio_referencia": lookup(lon, lat, neighborhoods, ("BARRIOCOMU", "NOMBRE")),
            "via_principal": main_road[0][0] if main_road else "",
            "via_secundaria": secondary_road[0][0] if secondary_road else "",
            "lugar": best[0][0] if best else "",
            "archivos_coordenada": coord_frequency,
            "total_archivos_nodo": len(candidates),
            "fuente_coordenada": matching[0]["archivo_fuente"],
        })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(f"Nodos con observaciones: {len(data_nodes)} · con coordenada válida: {len(rows)} · sin coordenadas: {len(data_nodes - set(by_node))}")
    print(f"Sin localidad: {sum(not row['localidad'] for row in rows)} · sin UPZ de referencia: {sum(not row['upz_referencia'] for row in rows)} · sin barrio: {sum(not row['barrio_referencia'] for row in rows)}")
    print(f"Catálogo: {OUTPUT}")


if __name__ == "__main__":
    main()
