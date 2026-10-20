# Snapshot público del dataset

`aforos_limpios.csv.gz` es una copia comprimida de `data/processed/aforos_limpios.csv`, generada por `src/publish_dataset.py` para que el dashboard tenga datos al desplegarse desde GitHub. Contiene observaciones limpias y nombres de archivo fuente; no incluye los Excel originales, los ZIP ni credenciales.

Después de actualizar fuentes, `python src/refresh_data.py` reconstruye este snapshot. Revisa el `git status` y publica el cambio del `.gz` junto con el código si quieres actualizar la versión en línea.
