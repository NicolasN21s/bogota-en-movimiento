# Diccionario de datos

## Fuente y alcance

Los ZIP se descargan manualmente del visor del Observatorio de Movilidad de Bogotá y se guardan en `data/incoming/`. El importador conserva los ZIP y extrae solo hojas `.xlsx` cuyos nombres indiquen estudios de volumen de bicicleta (`VOLB`) o vehículo (`VOL`). Omite peatones (`VOLP`), velocidad/dirección (`VD`) y otros tipos. Los duplicados con contenido idéntico se registran una sola vez.

La cobertura actual corresponde a los nodos incluidos en los ZIP escogidos por el usuario; no cubre toda Bogotá. El visor limita a 20 nodos por descarga, por lo que pueden usarse varios ZIP. Las fechas no son necesariamente las mismas entre nodos ni modalidades. El dashboard deja elegir nodo, modalidad y fechas.

## Columnas de `aforos_limpios.csv`

| Columna | Significado |
|---|---|
| `fecha` | Fecha del aforo (`AAAA-MM-DD`). Si la única fecha de la hoja está en el futuro y `Identificacion` declara una fecha pasada, se usa la fecha pasada de la ficha y se imprime una advertencia. Otras diferencias entre ambas fuentes se conservan para revisión, sin corregirlas automáticamente. |
| `hora` | Inicio del intervalo de 15 minutos (`HH:MM`). |
| `nodo` | Identificador del punto de aforo. |
| `modalidad` | `bicicleta` o `vehiculo`. |
| `categoria` | Categoría reconocida en la hoja de volumen. |
| `conteo` | Observación numérica de esa categoría e intervalo. Los conteos vacíos se omiten. |
| `sentido`, `acceso`, `movimiento` | Códigos reportados por la fuente. |
| `archivo_fuente` | Nombre del Excel usado para la fila. |

Las categorías vehiculares iniciales incluyen motos (`M`), livianos (`L`), buses (`B`), taxi y camiones. Los archivos recientes pueden usar códigos como `C2`, `C3`, `C4`, `AT` e `INT`; se conservan con el código de origen porque falta validar su etiqueta descriptiva oficial.

Para bicicletas se reconocen columnas totales o categorías simples como `BI`, `BI_CALZADA`, `BICI_CICLORUTA`, `BICI_BICICARRIL` y `BI-CEBRA`. Columnas desglosadas simultáneamente por perfil e infraestructura (por ejemplo `BI_INFRA_CALZADA_HOMBRE`) no se suman: podrían representar dimensiones superpuestas y contar dos veces una misma observación.

## Cobertura del estudio

`data/metadata/studies.csv` registra por archivo y modalidad la fecha, nodo, franjas esperadas, intervalo y códigos de movimiento de `Identificacion`. Algunas fichas antiguas carecen de franjas o movimientos legibles y por ello no generan cobertura calculable. La cobertura compara combinaciones intervalo–movimiento registradas con las declaradas; las franjas sin fila se consideran ausentes, no cero.

Los totales describen los conteos observados en los archivos seleccionados. Algunos nodos y fechas aparecen en más de un Excel con contenido distinto; esos archivos se conservan y el dashboard advierte cuando la selección suma más de una fuente para el mismo nodo-fecha-modalidad. Revisa esas versiones antes de usar el total como una estimación. Si se suman varios nodos, el resultado no equivale a personas únicas ni al total de viajes de la ciudad. El proyecto no atribuye causas a diferencias entre fechas.
# Catálogo geográfico de nodos

`data/metadata/nodes.csv` contiene los nodos del dataset limpio que tienen una coordenada válida en la hoja `Identificacion` de al menos un Excel. Cruza cada punto con las capas oficiales de localidad, UPZ y Barrio Común guardadas en `data/reference/`. Se elige la coordenada más repetida entre los archivos del nodo; el catálogo registra el número de archivos coincidentes y el Excel de referencia. En la versión actual hay 163 nodos ubicables de 172 nodos con observaciones; los nueve restantes se excluyen del mapa y el dashboard avisa cuando se seleccionan.

La localidad, UPZ y el nombre de Barrio Común solo se completan cuando el punto cae dentro del polígono correspondiente. UPZ se muestra como referencia territorial y no equivale al barrio ni necesariamente a la división de planeación vigente. El nombre de Barrio Común es una referencia cartográfica de la capa distrital, no una verificación en terreno ni una validación de nomenclatura vigente. Los resultados dependen de que la coordenada esté bien registrada en la ficha fuente.

# Actualización y almacenamiento

`python src/refresh_data.py` procesa los ZIP de `data/incoming/`, reconstruye la tabla limpia, los resúmenes y el catálogo de nodos. Los ZIP se descargan manualmente del visor por los límites de selección del portal. Si existe `DATABASE_URL` en `.env`, el mismo comando carga los hechos a PostgreSQL conservando `archivo_fuente`.
