"""Interactive first dashboard for the Bogotá en Movimiento project."""

from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
LOCAL_DATA_FILE = ROOT / "data" / "processed" / "aforos_limpios.csv"
PUBLIC_DATA_FILE = ROOT / "data" / "public" / "aforos_limpios.csv.gz"
DATA_FILE = LOCAL_DATA_FILE if LOCAL_DATA_FILE.exists() else PUBLIC_DATA_FILE
STUDIES_FILE = ROOT / "data" / "metadata" / "studies.csv"
NODES_FILE = ROOT / "data" / "metadata" / "nodes.csv"
MONTHS_ES = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}


st.set_page_config(
    page_title="Bogotá en Movimiento",
    page_icon="🚲",
    layout="wide",
)


@st.cache_data
def load_data(file_mtime_ns: int) -> pd.DataFrame:
    if not DATA_FILE.exists():
        raise FileNotFoundError("No existe el CSV limpio. Ejecuta primero: python src\\clean_data.py")
    data = pd.read_csv(DATA_FILE)
    data["fecha"] = pd.to_datetime(data["fecha"], errors="coerce")
    data["conteo"] = pd.to_numeric(data["conteo"], errors="coerce")
    return data.dropna(subset=["fecha", "hora", "conteo"])


@st.cache_data
def load_studies(file_mtime_ns: int) -> pd.DataFrame:
    if not STUDIES_FILE.exists():
        return pd.DataFrame()
    studies = pd.read_csv(STUDIES_FILE, dtype={"codigos_movimiento_esperados": "string"})
    studies["fecha"] = pd.to_datetime(studies["fecha"], errors="coerce")
    return studies


@st.cache_data
def load_nodes(file_mtime_ns: int) -> pd.DataFrame:
    if not NODES_FILE.exists():
        return pd.DataFrame()
    return pd.read_csv(NODES_FILE)


def node_location_label(point) -> str:
    parts = [
        f"Localidad {str(getattr(point, 'localidad')).title()}"
        for value in [getattr(point, "localidad", "")]
        if pd.notna(value) and str(value).strip()
    ]
    for field, label in [("upz_referencia", "UPZ"), ("barrio_referencia", "barrio")]:
        value = getattr(point, field, "")
        if pd.notna(value) and str(value).strip():
            parts.append(f"{label} {str(value).title()}")
    return " · ".join(parts) or "ubicación administrativa sin confirmar"


def pivot_with_time_gaps(frame: pd.DataFrame, columns: str) -> pd.DataFrame:
    wide = frame.pivot_table(index="hora", columns=columns, values="conteo", aggfunc="sum").sort_index()
    if wide.empty:
        return wide
    start = pd.to_datetime(wide.index.min(), format="%H:%M")
    end = pd.to_datetime(wide.index.max(), format="%H:%M")
    full_times = pd.date_range(start=start, end=end, freq="15min").strftime("%H:%M")
    return wide.reindex(full_times)


def format_date_es(value: pd.Timestamp, include_year: bool = True) -> str:
    date_text = f"{value.day:02d} {MONTHS_ES[value.month]}"
    return f"{date_text} {value.year}" if include_year else date_text


def compact_time_ranges(times: list[str], interval_minutes: int) -> str:
    if not times:
        return "ninguna"
    minutes = sorted(int(time[:2]) * 60 + int(time[3:]) for time in times)
    ranges = []
    first = previous = minutes[0]
    for current in minutes[1:]:
        if current != previous + interval_minutes:
            ranges.append((first, previous))
            first = current
        previous = current
    ranges.append((first, previous))

    labels = []
    for start, end in ranges:
        start_label = f"{start // 60:02d}:{start % 60:02d}"
        end_label = f"{end // 60:02d}:{end % 60:02d}"
        count = (end - start) // interval_minutes + 1
        labels.append(f"{start_label}–{end_label} ({count})" if start != end else start_label)
    return ", ".join(labels)


def summarize_coverage(study: pd.Series, study_rows: pd.DataFrame) -> dict:
    expected_times: set[str] = set()
    schedule_ranges = str(study["franjas_esperadas"]).split("|")
    for schedule_range in schedule_ranges:
        start_time, end_time = schedule_range.split("-", maxsplit=1)
        start = pd.Timestamp(f"{study['fecha']:%Y-%m-%d} {start_time}")
        end = pd.Timestamp(f"{study['fecha']:%Y-%m-%d} {end_time}")
        expected_times.update(
            pd.date_range(
                start=start, end=end, freq=f"{int(study['intervalo_minutos'])}min", inclusive="left"
            ).strftime("%H:%M")
        )
    expected_movements = str(study["codigos_movimiento_esperados"]).split("|")
    expected_pairs = {(time, movement) for time in expected_times for movement in expected_movements}

    observed_pairs = {
        (str(row.hora), str(row.movimiento))
        for row in study_rows[["hora", "movimiento"]].drop_duplicates().itertuples(index=False)
    }
    present_pairs = expected_pairs & observed_pairs
    missing_pairs = expected_pairs - present_pairs
    return {
        "expected": len(expected_pairs),
        "observed": len(present_pairs),
        "missing": len(missing_pairs),
        "percent": len(present_pairs) / len(expected_pairs) if expected_pairs else 0,
        "missing_times": sorted({time for time, _ in missing_pairs}),
        "interval_minutes": int(study["intervalo_minutos"]),
        "schedule": " / ".join(schedule_range.replace("-", "–") for schedule_range in schedule_ranges),
    }


def render_coverage(filtered_rows: pd.DataFrame, selected_modality: str | None, selected_dates: list[str]) -> None:
    studies_mtime = STUDIES_FILE.stat().st_mtime_ns if STUDIES_FILE.exists() else -1
    studies = load_studies(studies_mtime)
    if studies.empty:
        st.info("Agrega la ficha de cobertura en data/metadata/studies.csv para mostrar este indicador.")
        return

    studies = studies[studies["archivo_fuente"].isin(filtered_rows["archivo_fuente"].unique())]
    if selected_modality:
        studies = studies[studies["modalidad"] == selected_modality]
    if selected_dates:
        studies = studies[studies["fecha"].dt.strftime("%Y-%m-%d").isin(selected_dates)]

    st.subheader("Cobertura de los aforos")
    st.caption(
        "Compara las combinaciones intervalo–movimiento registradas con la franja y los movimientos declarados "
        "en la ficha de cada estudio. Los faltantes se muestran como datos ausentes, nunca como conteo cero."
    )
    if studies.empty:
        st.caption("No hay fichas de cobertura para esta selección.")
        return

    for study in studies.itertuples(index=False):
        study_rows = filtered_rows[filtered_rows["archivo_fuente"] == study.archivo_fuente]
        summary = summarize_coverage(pd.Series(study._asdict()), study_rows)
        title = f"{study.modalidad.title()} · {format_date_es(study.fecha)}"
        st.markdown(f"**{title}** · franja declarada {summary['schedule']}")
        st.progress(summary["percent"], text=f"{summary['percent']:.1%} · {summary['observed']} de {summary['expected']} combinaciones registradas")
        if summary["missing"]:
            missing_text = compact_time_ranges(summary["missing_times"], summary["interval_minutes"])
            st.caption(f"Sin registro: {summary['missing']} combinaciones; franjas con faltantes: {missing_text}.")
        else:
            st.caption("Todos los intervalos y movimientos esperados tienen registros en el archivo.")


if not DATA_FILE.exists():
    st.error("No existe el CSV limpio. Ejecuta primero: python src\\clean_data.py")
    st.stop()
data = load_data(DATA_FILE.stat().st_mtime_ns)
node_catalog = load_nodes(NODES_FILE.stat().st_mtime_ns if NODES_FILE.exists() else -1)
st.title("Bogotá en Movimiento")
st.caption("Explorador de aforos oficiales por intervalo, modalidad y movimiento.")

with st.sidebar:
    st.header("Filtros")
    node_values = sorted(int(node) for node in data["nodo"].dropna().unique())
    default_node = 26040 if 26040 in node_values else (node_values[0] if node_values else None)
    selected_nodes = st.multiselect(
        "Nodo(s) de aforo",
        node_values,
        default=[default_node] if default_node is not None else [],
        help="Elige una intersección por su código de nodo. Puedes seleccionar varios.",
    )
    if not node_catalog.empty and selected_nodes:
        selected_locations = node_catalog[node_catalog["nodo"].isin(selected_nodes)]
        for point in selected_locations.itertuples(index=False):
            roads = " × ".join(str(value) for value in [point.via_principal, point.via_secundaria] if pd.notna(value) and str(value).strip())
            st.caption(f"Nodo {point.nodo}: {node_location_label(point)}")
            if roads:
                st.caption(f"Vías: {roads}")
    modality_options = {
        "Todas las modalidades": None,
        "Bicicletas": "bicicleta",
        "Vehículos": "vehiculo",
    }
    modality_label = st.selectbox("Modalidad", list(modality_options), index=1)
    selected_modality = modality_options[modality_label]

    node_data = data[data["nodo"].isin(selected_nodes)] if selected_nodes else data.iloc[0:0]
    date_values = sorted(node_data["fecha"].dt.strftime("%Y-%m-%d").unique())
    default_dates = date_values[-3:]
    selected_dates = st.multiselect("Fecha del aforo", date_values, default=default_dates)

node_label = ", ".join(str(node) for node in selected_nodes) if selected_nodes else "ninguno"
st.markdown(f"### Aforos observados · nodo(s) {node_label}")

filtered = node_data.copy()
if selected_modality:
    filtered = filtered[filtered["modalidad"] == selected_modality]
if selected_dates:
    filtered = filtered[filtered["fecha"].dt.strftime("%Y-%m-%d").isin(selected_dates)]
else:
    filtered = filtered.iloc[0:0]

if selected_modality is None:
    st.warning(
        "Las modalidades tienen fechas y franjas de medición distintas. "
        "Usa el filtro para analizarlas por separado; los totales conjuntos no son una comparación simultánea."
    )
if len(selected_nodes) > 1:
    st.warning(
        "Los conteos suman registros de varias intersecciones seleccionadas. "
        "No representan personas únicas ni un total de viajes de Bogotá."
    )
source_versions = filtered.groupby(["fecha", "nodo", "modalidad"])["archivo_fuente"].nunique()
version_overlap_count = int((source_versions > 1).sum())
if version_overlap_count:
    st.warning(
        f"Hay {version_overlap_count:,} combinación(es) de fecha, nodo y modalidad con más de un archivo fuente. "
        "El gráfico suma sus filas; podrían ser versiones o estudios repetidos, así que valida esos casos antes de comparar totales."
    )
st.info(
    "Los valores muestran únicamente los intervalos presentes en los archivos. "
    "Los espacios sin filas no se interpretan como cero."
)

if not node_catalog.empty:
    mapped_nodes = node_catalog[node_catalog["nodo"].isin(selected_nodes)].copy()
    if not mapped_nodes.empty:
        st.subheader("Ubicación de las intersecciones")
        st.caption(
            "La localidad, UPZ y barrio de referencia se asignan desde las coordenadas de los Excel y capas distritales. "
            "La UPZ es referencia territorial y el nombre de Barrio Común depende de la capa distrital disponible. "
            "Solo se dibujan puntos con coordenadas válidas."
        )
        mapped_nodes["etiqueta"] = mapped_nodes.apply(
            lambda row: f"Nodo {int(row['nodo'])} · {node_location_label(row)}", axis=1
        )
        map_data = mapped_nodes.rename(columns={"latitude": "lat", "longitude": "lon"})
        layer = pdk.Layer(
            "ScatterplotLayer", data=map_data, get_position="[lon, lat]", get_radius=115,
            get_fill_color=[0, 104, 201, 210], pickable=True, auto_highlight=True,
        )
        labels = pdk.Layer(
            "TextLayer", data=map_data, get_position="[lon, lat]", get_text="etiqueta",
            get_size=12, get_color=[35, 48, 68, 255], get_alignment_baseline="bottom",
        )
        st.pydeck_chart(
            pdk.Deck(
                layers=[layer, labels],
                initial_view_state=pdk.ViewState(
                    latitude=float(mapped_nodes["latitude"].mean()),
                    longitude=float(mapped_nodes["longitude"].mean()),
                    zoom=10 if len(mapped_nodes) > 1 else 13,
                    pitch=0,
                ),
                tooltip={"text": "{etiqueta}\n{via_principal} × {via_secundaria}"},
                map_style="light",
            ),
            use_container_width=True,
        )
        st.dataframe(
            mapped_nodes[["nodo", "localidad", "upz_referencia", "barrio_referencia", "via_principal", "via_secundaria", "lugar"]],
            hide_index=True,
            use_container_width=True,
        )
        missing_node_ids = sorted(set(selected_nodes) - set(mapped_nodes["nodo"]))
        if missing_node_ids:
            st.warning(
                f"No se puede dibujar el/los nodo(s) {', '.join(map(str, missing_node_ids))}: "
                "sus fichas de origen no contienen coordenadas válidas."
            )
elif selected_nodes:
    st.warning("No hay coordenadas disponibles para los nodos seleccionados. Revisa sus fichas de origen.")

if filtered.empty:
    st.warning("No hay filas para los filtros seleccionados.")
    st.stop()

if len(selected_nodes) > 1:
    st.subheader("Comparación de conteos observados por nodo")
    st.caption(
        "Suma únicamente las filas presentes en los filtros actuales. Las fechas, franjas y cobertura pueden diferir entre nodos; "
        "interpreta este gráfico como conteo observado, no como una clasificación de tráfico comparable."
    )
    node_totals = filtered.groupby("nodo", as_index=False)["conteo"].sum()
    if not node_catalog.empty:
        node_totals = node_totals.merge(
            node_catalog[["nodo", "localidad", "upz_referencia", "barrio_referencia", "via_principal", "via_secundaria"]],
            on="nodo",
            how="left",
        )
        node_totals["interseccion"] = node_totals.apply(
            lambda row: f"{int(row['nodo'])} · {str(row.get('via_principal', '') or '').strip()} × "
            f"{str(row.get('via_secundaria', '') or '').strip()} · {node_location_label(row)}",
            axis=1,
        )
    else:
        node_totals["interseccion"] = node_totals["nodo"].astype(str)
    node_totals = node_totals.sort_values("conteo", ascending=False)
    st.bar_chart(node_totals, x="interseccion", y="conteo", x_label="Nodo / intersección", y_label="Conteo observado")

date_count = int(filtered["fecha"].nunique())

metric_cols = st.columns(3)
if selected_modality is None:
    bike_count = int(filtered.loc[filtered["modalidad"] == "bicicleta", "conteo"].sum())
    vehicle_count = int(filtered.loc[filtered["modalidad"] == "vehiculo", "conteo"].sum())
    metric_cols[0].metric("Bicicletas registradas", f"{bike_count:,}")
    metric_cols[1].metric("Vehículos registrados", f"{vehicle_count:,}")
else:
    total_observed = int(filtered["conteo"].sum())
    interval_count = int(filtered[["fecha", "hora", "sentido", "movimiento"]].drop_duplicates().shape[0])
    metric_cols[0].metric("Conteo observado", f"{total_observed:,}")
    metric_cols[1].metric(
        "Registros intervalo–movimiento",
        f"{interval_count:,}",
        help="Combinaciones registradas de fecha, hora y movimiento; no equivale al número de horarios únicos.",
    )
metric_cols[2].metric("Fechas con datos", f"{date_count}")

render_coverage(filtered, selected_modality, selected_dates)

st.subheader("Hallazgos automáticos")


def show_bike_findings(bike_rows: pd.DataFrame) -> None:
    st.markdown("**Bicicletas**")
    if bike_rows.empty:
        st.caption("No hay mediciones de bicicletas para las fechas seleccionadas.")
        return

    daily_totals = bike_rows.groupby("fecha")["conteo"].sum().sort_index()
    daily_peaks = (
        bike_rows.groupby(["fecha", "hora"], as_index=False)["conteo"]
        .sum()
        .sort_values(["fecha", "conteo"], ascending=[True, False])
        .groupby("fecha", as_index=False)
        .first()
    )
    if len(daily_totals) >= 2:
        first_date, last_date = daily_totals.index[0], daily_totals.index[-1]
        first_total, last_total = int(daily_totals.iloc[0]), int(daily_totals.iloc[-1])
        percent_change = (last_total - first_total) / first_total * 100 if first_total else 0
        cols = st.columns(3)
        cols[0].metric(f"Conteo observado · {format_date_es(first_date)}", f"{first_total:,}")
        cols[1].metric(f"Conteo observado · {format_date_es(last_date)}", f"{last_total:,}")
        cols[2].metric("Cambio entre fechas", f"{percent_change:+.1f}%")
        peaks_text = " · ".join(
            f"{format_date_es(row.fecha, include_year=False)}: pico {int(row.conteo):,} a las {row.hora}"
            for row in daily_peaks.itertuples(index=False)
        )
        st.caption(f"Picos por fecha: {peaks_text}. El cambio describe los conteos observados; no atribuye causas.")
    else:
        date = daily_totals.index[0]
        peak = daily_peaks.iloc[0]
        st.write(
            f"El {format_date_es(date)} se registraron **{int(daily_totals.iloc[0]):,} bicicletas** "
            f"en los intervalos disponibles. El pico fue de **{int(peak['conteo']):,}** a las **{peak['hora']}**."
        )


def show_vehicle_findings(vehicle_rows: pd.DataFrame) -> None:
    st.markdown("**Vehículos**")
    if vehicle_rows.empty:
        st.caption("No hay mediciones de vehículos para las fechas seleccionadas.")
        return

    total = vehicle_rows["conteo"].sum()
    category_totals = vehicle_rows.groupby("categoria")["conteo"].sum().sort_values(ascending=False)
    movement_totals = (
        vehicle_rows.groupby(["sentido", "movimiento"])["conteo"].sum().sort_values(ascending=False)
    )
    peak = (
        vehicle_rows.groupby(["fecha", "hora", "sentido", "movimiento"], as_index=False)["conteo"]
        .sum()
        .sort_values("conteo", ascending=False)
        .iloc[0]
    )
    top_category, top_movement = category_totals.index[0], movement_totals.index[0]
    cols = st.columns(3)
    cols[0].metric(
        "Categoría con más conteos",
        top_category.replace("_", " ").title(),
        f"{int(category_totals.iloc[0]):,} · {category_totals.iloc[0] / total:.1%}",
    )
    cols[1].metric(
        "Movimiento con más conteos",
        f"{top_movement[0]} · mov. {top_movement[1]}",
        f"{int(movement_totals.iloc[0]):,} · {movement_totals.iloc[0] / total:.1%}",
    )
    cols[2].metric(
        "Pico de 15 minutos",
        f"{int(peak['conteo']):,}",
        f"{format_date_es(peak['fecha'], include_year=False)} · {peak['hora']} · {peak['sentido']}",
    )
    st.caption("Los hallazgos resumen solo los intervalos y fechas incluidos en la selección.")


if selected_modality is None:
    bike_col, vehicle_col = st.columns(2)
    with bike_col:
        show_bike_findings(filtered[filtered["modalidad"] == "bicicleta"])
    with vehicle_col:
        show_vehicle_findings(filtered[filtered["modalidad"] == "vehiculo"])
elif selected_modality == "bicicleta":
    show_bike_findings(filtered)
else:
    show_vehicle_findings(filtered)

st.subheader("Flujo por intervalo de 15 minutos")
if selected_modality is None:
    left, right = st.columns(2)
    bike_rows = filtered[filtered["modalidad"] == "bicicleta"]
    vehicle_rows = filtered[filtered["modalidad"] == "vehiculo"]
    with left:
        st.markdown("**Bicicletas · por fecha**")
        bike_rows = bike_rows.copy()
        bike_chart = pivot_with_time_gaps(bike_rows, "fecha")
        bike_chart.columns = [format_date_es(column) for column in bike_chart.columns]
        st.line_chart(bike_chart, y_label="Bicicletas registradas", x_label="Hora")
    with right:
        st.markdown("**Vehículos · por sentido**")
        vehicle_interval = (
            vehicle_rows.groupby(["hora", "sentido"], as_index=False)["conteo"].sum()
            .pivot(index="hora", columns="sentido", values="conteo")
            .sort_index()
        )
        st.line_chart(vehicle_interval, y_label="Vehículos registrados", x_label="Hora")
else:
    interval = (
        filtered.groupby(["fecha", "hora", "sentido", "movimiento"], as_index=False)
        .agg(conteo=("conteo", "sum"))
    )
    interval["serie"] = interval.apply(
        lambda row: f"{row['fecha']:%Y-%m-%d} · {row['sentido']} · mov. {row['movimiento']}", axis=1
    )
    chart_data = interval.pivot_table(index="hora", columns="serie", values="conteo", aggfunc="sum").sort_index()
    st.line_chart(chart_data, y_label="Conteos registrados", x_label="Hora de inicio del intervalo")

if selected_modality == "vehiculo":
    left, right = st.columns(2)
    with left:
        st.subheader("Composición por categoría")
        category_totals = (
            filtered.groupby("categoria", as_index=False)["conteo"].sum().sort_values("conteo", ascending=False)
        )
        st.bar_chart(category_totals, x="categoria", y="conteo", x_label="Categoría", y_label="Conteos")
    with right:
        st.subheader("Conteo observado por movimiento")
        movement_totals = (
            filtered.groupby(["sentido", "movimiento"], as_index=False)["conteo"]
            .sum()
            .sort_values("conteo", ascending=False)
        )
        movement_totals["serie"] = movement_totals.apply(
            lambda row: f"{row['sentido']} · movimiento {row['movimiento']}", axis=1
        )
        st.bar_chart(movement_totals, x="serie", y="conteo", x_label="Sentido", y_label="Conteos")
elif selected_modality == "bicicleta":
    st.subheader("Conteo observado por fecha")
    st.caption("Suma de los intervalos disponibles en cada fecha; las franjas sin filas no se estiman.")
    bike_daily = filtered.groupby("fecha", as_index=False)["conteo"].sum()
    bike_daily["fecha"] = bike_daily["fecha"].dt.strftime("%Y-%m-%d")
    st.bar_chart(bike_daily, x="fecha", y="conteo", x_label="Fecha", y_label="Bicicletas registradas")

with st.expander("Ver registros filtrados"):
    st.dataframe(filtered.sort_values(["fecha", "hora", "sentido", "categoria"]), use_container_width=True)

st.caption(
    "Fuente: Observatorio de Movilidad de Bogotá. "
    "Aforos observados en los nodos seleccionados; fechas y cobertura horaria difieren por modalidad. "
    "Consulta docs/data_dictionary.md para conocer el detalle y las limitaciones."
)
