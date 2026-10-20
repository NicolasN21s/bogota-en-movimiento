"""Download official Bogotá locality and legacy UPZ boundary layers."""

from pathlib import Path
import json

import requests


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "reference"
LAYERS = {
    "localidades.geojson": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/localidad/MapServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson",
    "upz.geojson": "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/unidadplaneamientozonal/MapServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson",
}
BARRIOS_URL = "https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/entidadterritorial/MapServer/0/query"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in LAYERS.items():
        response = requests.get(url, timeout=90)
        response.raise_for_status()
        payload = response.json()
        if payload.get("type") != "FeatureCollection" or not payload.get("features"):
            raise ValueError(f"El servicio no devolvió una capa válida para {filename}")
        (OUTPUT_DIR / filename).write_text(response.text, encoding="utf-8")
        print(f"{filename}: {len(payload['features'])} polígonos oficiales descargados")

    # This layer exceeds the service's 2,000-feature page size, so request pages.
    params = {"where": "1=1", "returnCountOnly": "true", "f": "json"}
    response = requests.get(BARRIOS_URL, params=params, timeout=90)
    response.raise_for_status()
    total = int(response.json()["count"])
    features = []
    for offset in range(0, total, 2000):
        response = requests.get(
            BARRIOS_URL,
            params={
                "where": "1=1", "outFields": "*", "outSR": "4326", "f": "geojson",
                "resultOffset": offset, "resultRecordCount": 2000,
            },
            timeout=120,
        )
        response.raise_for_status()
        features.extend(response.json().get("features", []))
    if len(features) != total:
        raise ValueError(f"La capa de barrios devolvió {len(features)} de {total} elementos.")
    (OUTPUT_DIR / "barrios.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8"
    )
    print(f"barrios.geojson: {len(features)} polígonos distritales descargados")


if __name__ == "__main__":
    main()
