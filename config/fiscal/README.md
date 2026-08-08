# Semillas fiscales — documento de revisión

Este directorio contiene la configuración fiscal del Hub CFDI: la ley (estable y
verificable de un vistazo) y los valores que cambian por decreto (propuestos, con su
fuente, esperando que una persona los confirme).

**Este README no es documentación general: es la hoja de revisión.** Está escrito para que
quien conoce la materia pueda sentarse con la LISR, la LFT y la LSS al lado y decidir, valor
por valor, si la semilla dice la verdad. Lo que sigue está ordenado para esa sesión.

---

## 0. Lo primero: qué se aplica solo y qué no

| Archivo | ¿Se aplica al cargarlo? |
|---|---|
| `tabla_vacaciones.yaml` | **Sí, en cuanto se carga.** Es la transcripción de un artículo con dos columnas de enteros; su error de captura lo atrapa `test_la_tabla_de_vacaciones_reproduce_la_progresion_del_articulo_76`, que reconstruye la progresión desde el texto del artículo. **Esa red cubre el archivo del repo, no la fila de la base:** no protege contra editar el YAML en el servidor ni contra un `UPDATE` a mano. |
| `param_fiscal.yaml` | **No.** Cada valor queda pendiente de confirmación. `valor_vigente()` devuelve `None` hasta que alguien lo confirme. |
| `catalogo_percepcion.yaml` | **No.** Igual que arriba, y por una razón más fuerte: son 44 derivaciones a mano del art. 93 de la LISR. `marcas_de_percepcion()` solo devuelve las confirmadas. |
| `empresa*.yaml` (de la plantilla) | **Sí, en cuanto se carga.** Es configuración operativa de cada organización, no una cifra de la ley. |

Mientras un valor no esté confirmado, el informe que lo necesita **reporta el hueco con su
propuesta y su fuente** ("la UMA 2026 está propuesta con su liga al INEGI, confírmala"), en
vez de calcular con un cero. Cargar propone; confirmar es un acto humano y se hace desde la
pantalla de configuración, con nombre y fecha.

---

## 1. Advertencia que hay que leer antes de tocar cualquier archivo

> **Quitar un renglón de un YAML no borra la fila de la base de datos.**

El cargador inserta y actualiza; nunca borra. Si se siembra una marca equivocada, se carga,
y después se corrige quitando el renglón del archivo, **la fila equivocada sigue viva en la
base** y —si alguien alcanzó a confirmarla— sigue calculando. Para deshacer una semilla hay
que corregir el renglón en el YAML y volver a cargar (al cambiar el contenido, el cargador
limpia la confirmación previa y la fila vuelve a la cola de revisión), o borrarla desde la
pantalla de configuración. **Nunca "borrando el renglón y recargando".**

Dos consecuencias más del mismo diseño, útiles al revisar:

- **Recargar es idempotente y seguro.** La clave natural de cada tabla decide si el renglón
  se inserta o se actualiza; correr el script dos veces no duplica nada.
- **El cargador no pisa una corrección hecha a mano.** Un `param_fiscal` con `origen:
  MANUAL` que diga algo distinto del YAML se omite y se reporta en pantalla, en vez de
  escribirse. `--forzar` es la salida explícita para cuando la semilla debe ganar.

---

## 2. Cómo se cargan

```bash
# Los tres archivos globales (no llevan --empresa-id)
python -m app.scripts.cargar_configuracion_fiscal config/fiscal/tabla_vacaciones.yaml
python -m app.scripts.cargar_configuracion_fiscal config/fiscal/param_fiscal.yaml
python -m app.scripts.cargar_configuracion_fiscal config/fiscal/catalogo_percepcion.yaml

# Lo de cada organización (copia primero la plantilla, ver §6)
python -m app.scripts.cargar_configuracion_fiscal config/fiscal/empresa-acme.yaml --empresa-id 1
```

Dentro de los contenedores (`config/` está montado en `api` y en `worker`):

```bash
docker compose exec api python -m app.scripts.cargar_configuracion_fiscal config/fiscal/param_fiscal.yaml
```

El script valida el archivo **entero** antes de escribir el primer renglón, y escribe en una
sola transacción: o entra todo o no entra nada. Si la validación falla, sale con código 1 y
dice archivo, sección, renglón y campo. Un fallo al cargar es barato; media semilla aplicada,
no.

---

## 3. `param_fiscal.yaml` — los cinco valores 2026, con su fuente

Cada cifra se revisa abriendo la liga y comparándola. Nada más.

| Clave | Valor | Vigencia desde | Fuente |
|---|---|---|---|
| `UMA_DIARIA` | 117.31 | 2026-02-01 | INEGI, boletín UMA 2026 — https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2026/uma/uma2026.pdf |
| `UMA_MENSUAL` | 3 566.22 | 2026-02-01 | idem (117.31 × 30.4, redondeado a centavos) |
| `UMA_ANUAL` | 42 794.64 | 2026-02-01 | idem (= 3 566.22 × 12) |
| `SALARIO_MINIMO_GENERAL` | 315.04 | 2026-01-01 | DOF 09-12-2025, resolución del CONASAMI — https://www.dof.gob.mx/nota_detalle.php?codigo=5775534&fecha=09%2F12%2F2025 |
| `SALARIO_MINIMO_ZLFN` | 440.87 | 2026-01-01 | idem |

**Dos comprobaciones que se pueden hacer sin abrir nada.** La primera es la relación entre las
tres UMA, **con su redondeo**, que es donde está el detalle:

- `117.31 × 30.4 = 3 566.224`, que **redondeado a centavos** da la UMA mensual, `3 566.22`;
- `3 566.22 × 12 = 42 794.64`, y esto sí es exacto.

No se cumple encadenando sin redondear: `117.31 × 30.4 × 12 = 42 794.688`, que no es el valor
anual. El redondeo ocurre en el paso mensual, y así lo publica el INEGI. Con eso presente, un
dedazo en cualquiera de las tres cifras se detecta multiplicando.

La segunda: las fechas de vigencia **no coinciden a propósito**. La UMA cambia el 1 de
febrero y el salario mínimo el 1 de enero; ver dos fechas distintas en esta tabla es lo
correcto, no un error de captura.

**Por qué se siembran las dos zonas salariales.** Cuál aplica es política de cada organización
(`configuracion_empresa.zona_salarial`) y el servicio se niega a adivinarla. Ciudad Juárez
está en la Zona Libre de la Frontera Norte, donde el mínimo es ~40 % mayor: suponer "GENERAL"
convertiría en "cumple" a empleados que están por debajo del mínimo.

---

## 4. `tabla_vacaciones.yaml` — art. 76 de la LFT

Transcripción del art. 76 de la Ley Federal del Trabajo, reforma publicada en el DOF el
27-12-2022 y en vigor desde el 1 de enero de 2023. Verificado contra el PDF oficial de la
Cámara de Diputados (https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf):

> "…un periodo anual de vacaciones pagadas, que en ningún caso podrá ser inferior a doce días
> laborables, y que aumentará en dos días laborables, hasta llegar a veinte, por cada año
> subsecuente de servicios. **A partir del sexto año**, el periodo de vacaciones aumentará en
> dos días por cada cinco de servicios."

| Antigüedad | Días | | Antigüedad | Días |
|---|---|---|---|---|
| 1 | 12 | | 16–20 | 26 |
| 2 | 14 | | 21–25 | 28 |
| 3 | 16 | | 26–30 | 30 |
| 4 | 18 | | 31–35 | 32 |
| 5 | 20 | | 36–40 | 34 |
| 6–10 | 22 | | 41–45 | 36 |
| 11–15 | 24 | | 46–50 | 38 |

Los tramos de cinco años se capturan **solo en su primer año** (6, 11, 16, …) porque el
resolutor toma el mayor `anios_antiguedad` que no exceda la antigüedad consultada. Capturar
los años intermedios sería redundante y multiplicaría las oportunidades de teclear mal.

Con menos de un año cumplido el resolutor devuelve `None`, no cero: ese derecho es
proporcional (art. 77 LFT) y no sale de esta tabla.

---

## 5. `catalogo_percepcion.yaml` — las 44 marcas del §3.1

Los 44 tipos son **todos** los del catálogo real (`C75b_c_TipoPercepcion` de satcfdi),
enumerados con el propio catálogo: ninguno se inventó y ninguno falta. Las citas de la LISR y
de la LSS se verificaron contra los PDF oficiales de la Cámara de Diputados (LISR, última
reforma DOF 01-04-2024; LSS, última reforma DOF 15-01-2026), **no de memoria** — la numeración
de fracciones del art. 93 que circula en los resúmenes suele estar corrida.

### 5.1 Convenciones

- `factor_exencion` con `PORCENTAJE` está en **escala 0–100** (`'100'` = exento total,
  `'50'` = la mitad). No es una fracción. La convención la fija esta semilla.
- Todo va como `UMA_DIAS` y **ningún renglón usa `SM_DIAS`**, aunque el texto de la LISR siga
  diciendo "salario mínimo general": el art. 26-B constitucional (reforma DOF 27-01-2016) y su
  tercero transitorio ordenan que toda referencia al salario mínimo *como unidad de cuenta*
  se entienda hecha a la UMA.
- `es_provisionable` es verdadero solo en **002 (aguinaldo)** y **021 (prima vacacional)**.
  Ver §5.5 sobre las vacaciones.

### 5.2 Los cinco tipos que NO son ingreso ordinario

`022` Prima por antigüedad · `023` Pagos por separación · `025` Indemnizaciones ·
`039` Jubilaciones/pensiones/haberes de retiro · `044` idem en parcialidades.

Los tres primeros caen bajo el art. 95 de la LISR, que los agrupa literalmente ("primas de
antigüedad, retiro e indemnizaciones u otros pagos, por separación") y les da un cálculo
anual propio. Incluirlos en la base ordinaria **sobreestimaría la base anual del ISR** en la
columna 11 de B-05: un número inflado en la constancia de alguien que recibió una
indemnización.

### 5.3 Los 39 tipos con duda declarada — la lista completa

De 44 tipos, **39 llevan una duda declarada** y solo 5 no (`001`, `002`, `003`, `021`, `028`).
Es un número alto a propósito: el modelo de marcas es un booleano y un factor por tipo, y
buena parte del art. 93 no cabe ahí. **Es mejor una duda declarada que un factor inventado.**

> **Dónde vive cada duda (cambió en la ronda 2 de la tarea 4).** Ya no es un comentario
> `# REVISAR (0NN): ...` del YAML: es el campo **`nota_revision`** del propio renglón, que se
> carga a la columna `catalogo_percepcion_marca.nota_revision` y viaja en
> `GET /v1/configuracion/percepciones`. El motivo es que la pantalla de confirmación mostraba
> 44 botones "Confirmar" sin ninguna de estas 39 razones a la vista —pedía confirmar a ciegas
> justo lo que el invariante existe para impedir—, porque los comentarios no se cargan. Esta
> sección sigue siendo la lista agrupada por gravedad, útil para leer de corrido; **el texto
> que manda es el del campo**, y no se dejó una copia en comentario para que no diverjan.

#### A. Decisiones de régimen — empezar por aquí (1 tipo)

Cambian si el ingreso entra o no a la base ordinaria del ISR, que es el efecto más grande de
todo el archivo. Queda **uno solo**, y es el único donde hay ambigüedad real:

| Tipo | Nombre | Duda | Cómo está sembrado |
|---|---|---|---|
| `024` | Seguro de retiro | El art. 95 agrupa "primas de antigüedad, **retiro** e indemnizaciones" y el art. 93-XIII exenta lo obtenido **con cargo a la subcuenta** del seguro de retiro — pero este tipo suele registrar la *aportación patronal*, que es otra cosa, y el CFDI no las separa | ingreso ordinario, sin exención. Si en la organización se usa para pagos de retiro por separación, va `es_ingreso_ordinario: false` + `UMA_DIAS 90` |

> **Corregido en la ronda 1: `051`, `052` y `053`.** La primera versión de esta semilla los
> dejó como ingreso ordinario gravado "por prudencia", razonando que la lista verificada del
> plan eran cinco tipos y estos no estaban en ella. Eso confundía una lista de **verificación**
> (se comprobó que esos cinco están bien) con una lista **exhaustiva**. El catálogo del SAT no
> es ambiguo con estos tres: dice literalmente "derivados de jubilación en parcialidades",
> "obtengan una jubilación en parcialidades" y "una jubilación en una sola exhibición". Son
> pagos de jubilación, les alcanza el mismo régimen que al `044` y al `039`, y dejarlos
> gravados no era conservador: era la marca equivocada. Ahora están así:
>
> | Tipo | Régimen | Base |
> |---|---|---|
> | `051` | no ordinario, `UMA_DIAS 15` | art. 93-IV (parcialidades), como el `044` |
> | `052` | no ordinario, `UMA_DIAS 15` | art. 93-IV (parcialidades), como el `044` |
> | `053` | no ordinario, `UMA_DIAS 90` | art. 93-XIII vía art. 96-Bis (una sola exhibición), como el `039` |
>
> Siguen marcados `REVISAR`, pero ahora por la duda del **grupo C** (el factor es por año o
> por día, no del periodo), no por su régimen.

#### B. Sin base sólida en el art. 93 → sembrados GRAVADOS (8 tipos)

No encontré fracción que los exente y **no les inventé un factor**. Si la revisión decide que
sí son previsión social, hay que cambiarlos a `PORCENTAJE 100` **y** aplicarles el tope
conjunto del grupo D.

| Tipo | Nombre | Por qué quedó gravado |
|---|---|---|
| `013` | Cuotas sindicales pagadas por el patrón | No está en las fracciones VI ni VIII y no me parece "de naturaleza análoga". (Para el SBC sí hay texto: art. 27-II LSS excluye lo otorgado "para fines sociales de carácter sindical".) |
| `031` | Vales de gasolina | La gasolina no atiende una necesidad social del trabajador (art. 93-VIII) |
| `032` | Vales de ropa | Cuidado con la confusión: el art. 27-I LSS excluye la "ropa" **como instrumento de trabajo** (uniforme), no un vale entregado como prestación |
| `033` | Ayuda para renta | El art. 93-X exenta la *casa habitación proporcionada*, no una ayuda en efectivo |
| `036` | Ayuda para transporte | Criterio dividido entre previsión social análoga e ingreso gravado |
| `038` | Otros ingresos por salarios | Cajón de sastre: el tratamiento depende de qué se pagó. Exentar por default un concepto desconocido es la peor opción |
| `045` | Ingresos en acciones o títulos valor | `NINGUNA` es correcto (no hay exención), pero el art. 94-VII le da a las opciones sobre acciones una base y un momento de acumulación propios que este modelo no expresa |
| `048` | Habitación | Podría estar **exento** por el art. 93-X ("casas habitación proporcionadas a los trabajadores… cuando se reúnan los requisitos de deducibilidad"); no pude verificar los requisitos |

#### C. Factores que la ley NO expresa por periodo de pago (9 tipos)

El número capturado es el de la ley, pero el multiplicador no viene en el CFDI de nómina.
**Quien calcule la exención tiene que conseguirlo aparte, o el resultado será varias veces
menor que el legal.**

| Tipo | Factor sembrado | Lo que dice la ley |
|---|---|---|
| `020` Prima dominical | `UMA_DIAS 1` | 1 UMA **por cada domingo laborado** (art. 93-XIV) |
| `022` Prima por antigüedad | `UMA_DIAS 90` | 90 UMA **por cada año de servicio**; fracción de más de 6 meses cuenta como año completo (art. 93-XIII) |
| `023` Pagos por separación | `UMA_DIAS 90` | idem |
| `025` Indemnizaciones | `UMA_DIAS 90` | idem |
| `039` Jubilación en una sola exhibición | `UMA_DIAS 90` | 90 UMA **por año de contribución** (art. 93-XIII, al que remite el art. 96-Bis-IV) |
| `044` Jubilación en parcialidades | `UMA_DIAS 15` | tope **diario** de 15 UMA (art. 93-IV). En una nómina quincenal el tope real son 15 UMA × 15 días. Además el art. 93-V obliga a considerar *todas* las pensiones del trabajador, las pague quien las pague — dato que el Hub no tiene |
| `051` y `052` Jubilación en parcialidades a extrabajadores | `UMA_DIAS 15` | idem `044` |
| `053` Jubilación en una sola exhibición a extrabajadores | `UMA_DIAS 90` | idem `039` |

#### D. Exención sujeta al TOPE CONJUNTO de previsión social (6 tipos)

Penúltimo párrafo del art. 93: la exención de previsión social se limita a **1 UMA anual**
cuando el sueldo más la exención pasan de **7 UMA anuales**. Es un tope **por trabajador y por
año sobre la suma de varios tipos**, no un factor por tipo, y el modelo no puede expresarlo.
Estos seis llevan `PORCENTAJE 100` (la exención "en bruto") y **hay que aplicarles el tope
aparte**, o se exentará de más.

`015` Becas · `029` Vales de despensa · `030` Vales de restaurante · `034` Ayuda para
artículos escolares · `035` Ayuda para anteojos · `037` Ayuda para gastos de funeral

**Estos seis, y solo estos, llevan `sujeto_a_tope_conjunto: true` en el YAML y una columna
del mismo nombre en la base.** Es la ronda 1 de arreglos: antes la distinción vivía solo en
los comentarios del YAML, y los comentarios no se cargan — un informe no tenía forma de
distinguir estos seis de los otros diez tipos con base `PORCENTAJE`, y la única salida habría
sido llevar la lista escrita en el código, que es una lista fiscal codificada en el programa
(lo que prohíbe el §2.12). **Al revisar, revisa el campo, no solo esta lista.**

> El mismo párrafo **exceptúa** del tope a: jubilaciones, pensiones y haberes de retiro,
> indemnizaciones por riesgos de trabajo o enfermedades, reembolsos de gastos médicos y de
> funeral, seguros de gastos médicos, seguros de vida y **fondos de ahorro**. Por eso `004`,
> `005`, `011`, `012` y `026` **no** están en esta lista aunque sean previsión social.
>
> **`006` Caja de ahorro es un caso aparte y merece su renglón de duda.** Se sembró como
> exceptuado, igual que el `005`, porque es lo habitual — pero el texto dice "fondos de
> ahorro" y **no menciona las cajas de ahorro**. Si la revisión decide atenerse a la letra,
> hay que agregarle `sujeto_a_tope_conjunto: true`. Está anotado en su comentario del YAML.

De estos, el que menos seguro me tiene es **`030` Vales de restaurante**: la fracción VIII no
los nombra y su analogía con la despensa es discutible — la despensa sí tiene exclusión propia
de SBC (art. 27-VI LSS), los vales de restaurante no.

#### E. Exención condicionada a algo que el CFDI no informa (10 tipos)

Se sembró suponiendo que la condición se cumple, porque es el caso normal.

| Tipo | Condición que no se puede verificar |
|---|---|
| `004` Reembolso de gastos médicos | "que se concedan de manera general" (art. 93-VI) |
| `005` Fondo de ahorro | requisitos de deducibilidad del art. 27-XI LISR (generalidad, aportación pareja, tope del 13 %) |
| `006` Caja de ahorro | idem; si la caja es de los trabajadores, el reintegro del ahorro propio no es ingreso y no debería ir como percepción; y el texto que exceptúa del tope conjunto dice "fondos de ahorro", no "cajas" (ver el recuadro del grupo D) |
| `011` Prima de seguro de vida | dos dudas: (a) el art. 93 exenta lo que **la aseguradora paga**, y que la **prima** pagada por el patrón no sea ingreso es criterio de previsión social; (b) el `integra_sbc: false` **no tiene la cita que decía tener** — el art. 27-VIII LSS define "fines sociales" de forma cerrada ("fondos de algún plan de pensiones") y una prima de seguro de vida no lo es, así que la regla general del art. 27 apuntaría a `true` |
| `012` Seguro de gastos médicos mayores | idem, más la condición de generalidad |
| `014` Subsidios por incapacidad | si es por **riesgo de trabajo** está exceptuado del tope (art. 93-III); si es por enfermedad general es previsión social con tope (art. 93-VIII). El nodo de percepciones no lo dice |
| `026` Reembolso por funeral | "de manera general, de acuerdo con las leyes o contratos de trabajo" (art. 93-VI) |
| `035` Ayuda para anteojos | de qué fracción venga cambia el resultado: la VI está exceptuada del tope conjunto, la VIII no |
| `037` Ayuda para gastos de funeral | la fracción VI habla de **reembolso** (para eso está el `026`); una *ayuda* no condicionada a comprobar el gasto podría no calificar |
| `050` Viáticos | exentos solo "cuando sean efectivamente erogados en servicio del patrón y se compruebe… con los comprobantes fiscales" (art. 93-XVII). Un viático no comprobado es gravado |

#### F. `integra_sbc` es booleano y varias exclusiones del art. 27 LSS son PARCIALES (9 tipos)

El art. 27 de la LSS dice que **todo** integra salvo nueve exclusiones tasadas, y su penúltimo
párrafo aclara que en varias de ellas "solamente se integrarán los excedentes". Un booleano no
expresa un tope: se capturó el caso típico.

| Tipo | Regla real |
|---|---|
| `009` Contribuciones del trabajador pagadas por el patrón | sembrado `true`; hay criterio de que absorber una contribución no incrementa el SBC |
| `010` Premios por puntualidad | art. 27-VII: excluido hasta el **10 % del SBC**; el excedente integra. Sembrado `true` |
| `019` Horas extra | art. 27-IX: excluido **dentro de los márgenes de la LFT** (9 h/semana); el excedente integra. Sembrado `false` |
| `027` Cuotas de seguridad social pagadas por el patrón | la exención del ISR es limpia (art. 93-XII, sin condiciones). La duda es solo el SBC: el art. 27-IV excluye las cuotas **del patrón**, y aquí se trata de la cuota **obrera** que el patrón absorbe. Sembrado `false` |
| `029` Vales de despensa | art. 27-VI: excluido hasta el **40 % del salario mínimo diario**. Sembrado `false` |
| `046` Ingresos asimilados a salarios | no hay relación laboral, así que no hay SBC; confirmar además que B-05 los quiera en la base ordinaria |
| `047` Alimentación | art. 27-V: excluido solo si es **onerosa** (el trabajador paga ≥ 20 % del SM diario). Sembrado `true` (gratuita) |
| `048` Habitación · `049` Premios por asistencia | idem 047 y idem 010 respectivamente |

### 5.4 Los 5 tipos sin duda declarada

`001` Sueldos · `002` Aguinaldo (30 UMA, art. 93-XIV) · `003` PTU (15 UMA, art. 93-XIV;
excluido del SBC por el art. 27-IV LSS) · `021` Prima vacacional (15 UMA, art. 93-XIV) ·
`028` Comisiones (gravadas; "comisiones" aparece literalmente entre los integrantes del SBC
en el art. 27, primer párrafo, LSS).

### 5.5 Las vacaciones no tienen tipo de percepción propio

El catálogo `c_TipoPercepcion` **no trae un tipo para vacaciones**: se pagan dentro del `001`
(Sueldos, Salarios Rayas y Jornales). Por eso `es_provisionable` es verdadero solo en `002` y
`021`, y **la provisión de vacaciones de B-08 no puede salir de este archivo**: tiene que
salir de `map_concepto_provision` en el YAML de cada organización, usando la clave interna que
el patrón le da al concepto. Está explicado en la plantilla `empresa.yaml.ejemplo`.

---

## 6. `empresa.yaml.ejemplo` — plantilla por organización

Se copia **sin el sufijo** y se carga con `--empresa-id`:

```bash
cp config/fiscal/empresa.yaml.ejemplo config/fiscal/empresa-acme.yaml
# editar con los datos reales
python -m app.scripts.cargar_configuracion_fiscal config/fiscal/empresa-acme.yaml --empresa-id 1
```

Todos los valores de la plantilla son **ficticios** y solo muestran la forma del archivo. Trae
las tres secciones por empresa: `configuracion_empresa` (zona salarial, días de aguinaldo,
factor de prima vacacional), `map_departamento` y `map_concepto_provision`.

Los tres campos de `configuracion_empresa` **no tienen valor por omisión**, a propósito: la
LFT pone pisos (15 días de aguinaldo, art. 87; prima vacacional de 0.25, art. 80), no valores
únicos, y la zona salarial cambia el resultado de una validación de cumplimiento. Un hueco
visible es mejor que un default plausible.

---

## 7. Qué falta por capturar, y quién

| Falta | Por qué importa | Quién |
|---|---|---|
| **Los valores 2025 de `param_fiscal`** | La UMA cambia el 1 de febrero: del **1 al 31 de enero de 2026** aplica todavía la UMA 2025. Hoy `valor_vigente('UMA_DIARIA', 2026-01-15)` devuelve `None` y el informe reporta el hueco. Al capturarlos hay que **cerrar** el tramo 2025 con `vigencia_hasta: 2026-01-31`, o el cargador rechazará el solapamiento | dueño del repo, con el boletín INEGI 2025 y el DOF del salario mínimo 2025 |
| **`TIPO_CAMBIO_USD`** | Cambia todos los días hábiles: no es una semilla. Lo llena la sincronización con el DOF. **No se sembró un valor "de ejemplo" a propósito**: un tipo de cambio viejo y confirmado es peor que la ausencia del dato | la sincronización automática |
| **Confirmar los 5 valores de `param_fiscal`** | Sin confirmar no calculan | dueño del repo, desde la pantalla de configuración |
| **Revisar y confirmar las 44 marcas**, empezando por el grupo A (`024`) y el grupo D (el tope conjunto) | Sin confirmar, B-05 reporta `FALTA_CATALOGO_DE_MARCAS` en vez de calcular | dueño del repo |
| **Un `empresa-*.yaml` por organización** | Sin `zona_salarial` no hay validación de salario mínimo; sin `map_concepto_provision` no hay provisión de vacaciones en B-08 | quien administra cada organización |

---

## 7 bis. Deuda de esquema conocida: las variantes ortográficas de `departamento_texto`

**Esto no se arregla desde ningún archivo de este directorio: exige una migración.** Queda escrito
aquí para que no se descubra en vivo.

`nomina_receptor.departamento` y `map_departamento.departamento_texto` viven en
`utf8mb4_unicode_ci`, que es **PAD SPACE** y no distingue mayúsculas (ni acentos). Consecuencia:
para MySQL, `'EDIFICIOS'`, `'Edificios'` y `'Edificios '` son **la misma clave primaria**.

Lo que ya está mitigado (y lo que no):

| pieza | antes | ahora |
|---|---|---|
| enumerar los departamentos observados | agrupaba con la colación de la columna: las tres variantes colapsaban en un renglón con la suma de sus CFDI | agrupa con `utf8mb4_0900_bin` (la única **NO PAD** de las tres): cada variante es su propio renglón, en la pantalla y en `administrar_configuracion observados` |
| el contador `sin_mapear` | se calculaba sobre la lista colapsada y llegaba a cero | cuenta las variantes de verdad, así que ya no dice "ya están todos agrupados" cuando B-06 va a quejarse |
| capturar la segunda variante | `IntegrityError` 1062 → 500 opaco | `422 MAPEO_COLISION_DE_CLAVE`, con el valor duplicado que reporta MySQL y la explicación |
| **poder mapear las dos** | imposible | **sigue siendo imposible** |

Por qué sigue siendo imposible: la escritura usa las reglas de la base (una fila por clave, y las
variantes comparten clave) mientras la lectura es un `dict` de Python (`cfg.centro_de_costo`), que
sí las distingue. Así que se puede mapear **una** variante y la otra seguirá cayendo al texto crudo
en B-06, sin forma de capturarla. Es el mismo residuo que declara el docstring de
`app/informes/b06_centro_costo.py`.

**Lo que NO se hizo, a propósito:** normalizar el texto (plegar mayúsculas, recortar espacios) para
que las variantes se traten como un solo departamento. Eso haría que el sistema decidiera un hecho
contable —"estos dos son el mismo centro de costo"— a partir de un parecido tipográfico, y es
exactamente el criterio que B-06 rechazó al elegir su llave de agrupamiento. Unificar variantes es
para lo que existe `map_departamento`; hacerlo por debajo esconde el problema que el mapeo resuelve.

### El arreglo de fondo

Dos opciones, y hay que elegir una antes de que haya muchos mapeos capturados:

1. **Migrar la columna a colación binaria NO PAD** (`utf8mb4_0900_bin`) en
   `map_departamento.departamento_texto` — y, por coherencia, en `nomina_receptor.departamento`.
   Cada variante pasa a ser mapeable por separado y el operador decide qué hacer con cada una.
   Es la opción coherente con "el texto del departamento es un dato opaco del patrón".
2. **Añadir una columna normalizada con su índice único** y dejar la original como se recibió. Más
   invasiva y obliga a definir la normalización en el esquema (que es donde tendría que estar si se
   eligiera este camino, no en Python).

**Qué hacer con lo ya capturado.** Con la opción 1 la migración es compatible hacia atrás: las
filas existentes siguen siendo válidas y su clave no cambia; lo único que aparece es la
**posibilidad** de insertar variantes que antes se rechazaban. No hay que reescribir nada ni
reprocesar informes. Antes de correrla conviene listar los grupos con variantes para revisarlos a
mano, porque después van a ser mapeables por separado y alguien tiene que decidir si de verdad son
departamentos distintos:

```sql
SELECT c.empresa_id,
       MIN(r.departamento) AS clave_actual,
       COUNT(DISTINCT r.departamento COLLATE utf8mb4_0900_bin) AS variantes,
       GROUP_CONCAT(DISTINCT CONCAT('[', r.departamento COLLATE utf8mb4_0900_bin, ']')) AS formas
  FROM nomina_receptor r
  JOIN comprobantes c ON c.comprobante_id = r.comprobante_id
 WHERE r.departamento IS NOT NULL AND c.tipo_comprobante = 'N'
 GROUP BY c.empresa_id, r.departamento
HAVING variantes > 1;
```

Al 2026-08-07 esa consulta no devuelve nada en la base real: los dos únicos textos son `EDIFICIOS`
y `SOCIAL`, sin variantes. Es blindaje, no incidente — pero se activa en cuanto aparezca la primera.

## 8. Qué verifican las pruebas y qué no

`tests/test_semillas_fiscales.py` (7 pruebas) **no valida la corrección fiscal** —eso es
exactamente lo que hace la persona que lee este documento—. Valida coherencia interna:

- la tabla de vacaciones arranca en 12 días, nunca decrece y llega a 20;
- toda clave de catálogo es texto de tres posiciones (`'022'`, no el entero 22);
- una base de exención distinta de `NINGUNA` trae factor positivo, y `NINGUNA` no trae factor;
- los cinco tipos del régimen de separación/jubilación no son ingreso ordinario;
- todo `param_fiscal` declara una fuente con liga o fecha, no una genérica;
- toda `nota_revision` dice **de qué tipo** es la duda;
- las tres semillas se cargan y **ninguna queda confirmada**.

Un factor de exención mal capturado no lo atrapa ninguna prueba. Por eso existe este README.

---

## Apéndice · Las 44 marcas de un vistazo

Generado desde `catalogo_percepcion.yaml`, para poder verificar un tipo sin abrir el YAML.
Los nombres son los del catálogo `c_TipoPercepcion`. El detalle de **por qué** cada marca es
lo que es, y la duda de cada tipo, están en el comentario del renglón correspondiente del
YAML; aquí solo está el resultado.

Lectura de las columnas: **Ord.** = `es_ingreso_ordinario` · **Factor** = `factor_exencion`
(días con `UMA_DIAS`, porcentaje 0–100 con `PORCENTAJE`) · **Tope** =
`sujeto_a_tope_conjunto` · **SBC** = `integra_sbc` · **Prov.** = `es_provisionable`.

| Tipo | Nombre | Ord. | Base exención | Factor | Tope | SBC | Prov. | `REVISAR` |
|---|---|---|---|---|---|---|---|---|
| `001` | Sueldos, Salarios Rayas y Jornales | sí | NINGUNA | — | — | sí | — | — |
| `002` | Gratificación Anual (Aguinaldo) | sí | UMA_DIAS | 30 | — | sí | sí | — |
| `003` | Participación de los Trabajadores en las Ut… | sí | UMA_DIAS | 15 | — | — | — | — |
| `004` | Reembolso de Gastos Médicos Dentales y Hosp… | sí | PORCENTAJE | 100 | — | — | — | **sí** |
| `005` | Fondo de Ahorro | sí | PORCENTAJE | 100 | — | — | — | **sí** |
| `006` | Caja de ahorro | sí | PORCENTAJE | 100 | — | — | — | **sí** |
| `009` | Contribuciones a Cargo del Trabajador Pagad… | sí | NINGUNA | — | — | sí | — | **sí** |
| `010` | Premios por puntualidad | sí | NINGUNA | — | — | sí | — | **sí** |
| `011` | Prima de Seguro de vida | sí | PORCENTAJE | 100 | — | — | — | **sí** |
| `012` | Seguro de Gastos Médicos Mayores | sí | PORCENTAJE | 100 | — | — | — | **sí** |
| `013` | Cuotas Sindicales Pagadas por el Patrón | sí | NINGUNA | — | — | — | — | **sí** |
| `014` | Subsidios por incapacidad | sí | PORCENTAJE | 100 | — | — | — | **sí** |
| `015` | Becas para trabajadores y/o hijos | sí | PORCENTAJE | 100 | sí | — | — | **sí** |
| `019` | Horas extra | sí | PORCENTAJE | 50 | — | — | — | **sí** |
| `020` | Prima dominical | sí | UMA_DIAS | 1 | — | sí | — | **sí** |
| `021` | Prima vacacional | sí | UMA_DIAS | 15 | — | sí | sí | — |
| `022` | Prima por antigüedad | — | UMA_DIAS | 90 | — | — | — | **sí** |
| `023` | Pagos por separación | — | UMA_DIAS | 90 | — | — | — | **sí** |
| `024` | Seguro de retiro | sí | NINGUNA | — | — | — | — | **sí** |
| `025` | Indemnizaciones | — | UMA_DIAS | 90 | — | — | — | **sí** |
| `026` | Reembolso por funeral | sí | PORCENTAJE | 100 | — | — | — | **sí** |
| `027` | Cuotas de seguridad social pagadas por el p… | sí | PORCENTAJE | 100 | — | — | — | **sí** |
| `028` | Comisiones | sí | NINGUNA | — | — | sí | — | — |
| `029` | Vales de despensa | sí | PORCENTAJE | 100 | sí | — | — | **sí** |
| `030` | Vales de restaurante | sí | PORCENTAJE | 100 | sí | — | — | **sí** |
| `031` | Vales de gasolina | sí | NINGUNA | — | — | sí | — | **sí** |
| `032` | Vales de ropa | sí | NINGUNA | — | — | sí | — | **sí** |
| `033` | Ayuda para renta | sí | NINGUNA | — | — | sí | — | **sí** |
| `034` | Ayuda para artículos escolares | sí | PORCENTAJE | 100 | sí | — | — | **sí** |
| `035` | Ayuda para anteojos | sí | PORCENTAJE | 100 | sí | — | — | **sí** |
| `036` | Ayuda para transporte | sí | NINGUNA | — | — | sí | — | **sí** |
| `037` | Ayuda para gastos de funeral | sí | PORCENTAJE | 100 | sí | — | — | **sí** |
| `038` | Otros ingresos por salarios | sí | NINGUNA | — | — | sí | — | **sí** |
| `039` | Jubilaciones, pensiones o haberes de retiro | — | UMA_DIAS | 90 | — | — | — | **sí** |
| `044` | Jubilaciones, pensiones o haberes de retiro… | — | UMA_DIAS | 15 | — | — | — | **sí** |
| `045` | Ingresos en acciones o títulos valor que re… | sí | NINGUNA | — | — | sí | — | **sí** |
| `046` | Ingresos asimilados a salarios | sí | NINGUNA | — | — | — | — | **sí** |
| `047` | Alimentación | sí | NINGUNA | — | — | sí | — | **sí** |
| `048` | Habitación | sí | NINGUNA | — | — | sí | — | **sí** |
| `049` | Premios por asistencia | sí | NINGUNA | — | — | sí | — | **sí** |
| `050` | Viáticos | sí | PORCENTAJE | 100 | — | — | — | **sí** |
| `051` | Pagos por gratificaciones, primas, compensa… | — | UMA_DIAS | 15 | — | — | — | **sí** |
| `052` | Pagos que se realicen a extrabajadores que … | — | UMA_DIAS | 15 | — | — | — | **sí** |
| `053` | Pagos que se realicen a extrabajadores que … | — | UMA_DIAS | 90 | — | — | — | **sí** |
