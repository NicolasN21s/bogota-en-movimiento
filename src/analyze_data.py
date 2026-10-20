"""Create interval and observed-period summaries from the cleaned CSV."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = ROOT / "data" / "processed" / "aforos_limpios.csv"
OUTPUT_DIR = ROOT / "data" / "processed"

GROUP_COLUMNS = ["fecha", "hora", "modalidad", "sentido", "acceso", "movimiento"]


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"No encontré {INPUT_FILE}. Ejecuta primero: python src\\clean_data.py")

    data = pd.read_csv(INPUT_FILE)
    # Consolidate vehicle categories within each interval while keeping each
    # recorded direction/access/movement as a separate series.
    by_interval = (
        data.groupby(GROUP_COLUMNS, dropna=False, as_index=False)
        .agg(conteo_observado=("conteo", "sum"), categorias_incluidas=("categoria", "nunique"))
        .sort_values(GROUP_COLUMNS)
    )
    by_interval.to_csv(OUTPUT_DIR / "resumen_por_intervalo.csv", index=False, encoding="utf-8-sig")

    by_period = (
        by_interval.groupby(["fecha", "modalidad", "sentido", "acceso", "movimiento"], dropna=False)
        .agg(
            conteo_observado=("conteo_observado", "sum"),
            intervalos_registrados=("hora", "nunique"),
            primera_hora=("hora", "min"),
            ultima_hora=("hora", "max"),
        )
        .reset_index()
        .sort_values(["fecha", "modalidad", "sentido", "acceso", "movimiento"])
    )
    by_period.to_csv(OUTPUT_DIR / "resumen_por_fecha_modalidad.csv", index=False, encoding="utf-8-sig")

    print("Resumen por fecha, modalidad, sentido y movimiento:")
    print(by_period.to_string(index=False))
    print("\nArchivos generados:")
    print(OUTPUT_DIR / "resumen_por_intervalo.csv")
    print(OUTPUT_DIR / "resumen_por_fecha_modalidad.csv")


if __name__ == "__main__":
    main()
