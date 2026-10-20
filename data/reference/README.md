# Límites geográficos de referencia

`localidades.geojson`, `upz.geojson` y `barrios.geojson` provienen de los servicios oficiales ArcGIS REST de Catastro Distrital / IDECA. El script `src/download_geo_reference.py` puede volver a descargarlos.

- Localidades: https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/localidad/MapServer/0
- UPZ: https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/unidadplaneamientozonal/MapServer/0
- Barrio común: https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/entidadterritorial/MapServer/0
- Sistema de salida: coordenadas geográficas WGS 84 (EPSG:4326).

Las UPZ se conservan como referencia territorial histórica de los aforos. No equivalen a barrios y no deben presentarse como la división de planeación vigente bajo el POT actual. La capa de Barrio Común asigna un nombre solo cuando existe una coincidencia espacial; se presenta como referencia cartográfica y puede dejar puntos sin barrio. La cobertura/actualidad de las capas depende del servicio fuente.
