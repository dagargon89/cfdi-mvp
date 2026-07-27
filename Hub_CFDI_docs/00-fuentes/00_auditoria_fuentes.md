# 00 — Auditoría de Fuentes

| Campo | Valor |
|---|---|
| Documento | 00 — Auditoría de Fuentes |
| Proyecto | Hub CFDI — Plataforma Web de Descarga Masiva y Cumplimiento CFDI |
| Versión | 2.0 |
| Fecha | 2026-07-27 |
| Depende de | [`investigacion_ezaudita.md`](investigacion_ezaudita.md) · [`inventario_funcional.md`](inventario_funcional.md) · [`../../CFDI-app-Escritorio/`](../../CFDI-app-Escritorio/) (documentación v1.0 archivada) |
| Propósito | Registro de hallazgos previo a la Fase 0 v2.0. No modifica las fuentes. |

Auditoría previa a la regeneración documental (Gobernanza v3.0, mejora 1) tras el pivote de escritorio a plataforma web multicliente/empresa. Fuentes: la investigación de ezaudita® (referencia funcional de paridad), el inventario funcional con viabilidad, y la documentación v1.0 archivada (que aporta el diseño del dominio ya auditado — sus hallazgos H-01…H-11 originales se consideran resueltos o heredados según el inventario).

**Resultado global:** las fuentes son suficientes para iniciar la Fase 0 v2.0. Se identifican **8 hallazgos**; ninguno bloquea la documentación. Dos (H-01, H-04) bloquean funciones específicas de releases futuros y ya están faseadas fuera del MVP por las prioridades definidas por David (seguridad/auth → núcleo de escritorio → complementos MVP → futuro).

---

## 1. Tabla resumen

| ID | Hallazgo | Fuente / sección | Severidad |
|---|---|---|---|
| H-01 | Conciliación del precargado de IVA sin mecanismo técnico conocido (no hay WS oficial) | Investigación §C9 · Inventario N-07/D6 | 🟠 Media (post-MVP) |
| H-02 | Custodia de e.firma en servidor: ezaudita lo hace, pero invierte el modelo de seguridad v1.0 | Investigación §técnica · Inventario P-02/E-03 | 🔴 Crítica (MVP) |
| H-03 | Motor fiscal IVA/ISR sin validador designado | Inventario N-06/N-08/D5 | 🟠 Media (post-MVP) |
| H-04 | Opinión de Cumplimiento sin confirmación de soporte en `satcfdi` | Inventario N-18 | 🟡 Baja (post-MVP) |
| H-05 | D4 (interna vs comercializable) indefinida | Inventario D4 | 🟠 Media |
| H-06 | Cifras de ezaudita (2,900M CFDI, 90k empresas) son marketing no verificado | Investigación (caveats) | 🟢 Informativo |
| H-07 | Dimensionamiento: referencia de mercado 1M CFDI/RFC como límite estándar | Investigación §planes | 🟡 Baja |
| H-08 | D1/D2 (nomenclatura y comprobante) siguen abiertas desde v1.0 | Inventario E-13/E-14 | 🟡 Baja |

---

## 2. Detalle de hallazgos

### H-01 · Precargado de IVA sin vía técnica confirmada 🟠
- **Situación:** ezaudita afirma conciliar el prellenado del SAT, pero no existe WS oficial documentado del precargado. Replicarlo podría implicar scraping frágil del visor.
- **Propuesta:** excluir del MVP (ya lo está: R3). Investigación D6 antes de comprometerla en cualquier SRS futuro; mientras, variante "conciliación contra archivo descargado del visor por el usuario".
- **Acción:** el SRS v2.0 la lista solo en consideraciones futuras, condicionada a D6.

### H-02 · Custodia de e.firma en el servidor 🔴
- **Situación:** el modelo web exige almacenar `.cer`/`.key`/contraseña de terceros en el servidor (ezaudita lo hace en AWS). La regla v1.0 "la FIEL nunca sale del equipo" muere. Es el activo más crítico del sistema: su filtración permite suplantar la identidad legal de los clientes.
- **Propuesta:** bóveda cifrada con envelope encryption (llave maestra fuera de la BD), acceso auditado en bitácora, descifrado solo en memoria del worker al construir el `Signer`. Prioridad 1 de David (seguridad primero) — se diseña **antes** que cualquier función de negocio.
- **Acción:** ADR-003 §6 y doc 04 (documento más profundo del proyecto); RF-BOV en el SRS; Sprint 1 del roadmap.

### H-03 · Motor fiscal sin validador 🟠
- **Situación:** IVA 4.0 e ISR a flujo son algoritmos fiscales delicados; un cálculo erróneo con apariencia correcta es el peor escenario del producto.
- **Propuesta:** D5 — designar a Pedro como validador fiscal (algoritmos + casos de prueba reales) antes de diseñar R3.
- **Acción:** fuera del MVP; el doc 07 lo condiciona a D5 cerrada.

### H-04 · Opinión de Cumplimiento sin confirmar 🟡
- **Situación:** la CSF está confirmada como nativa en `satcfdi`; la Opinión de Cumplimiento no.
- **Acción:** spike técnico en R2; no se compromete en el SRS del MVP.

### H-05 · D4 interna vs comercializable 🟠
- **Situación:** al ser multicliente (no multi-tenant), comercializar implicaría instancia por despacho/licencia. La respuesta cambia LFPDPPP (responsable vs encargado), términos de servicio y N-22.
- **Propuesta:** el MVP se documenta como **plataforma interna** (supuesto explícito, menor exigencia); si D4 cambia a comercial, se levanta un ADR con el delta (aviso de privacidad, contratos de resguardo, licenciamiento).
- **Acción:** supuesto registrado en SRS §2.3; N-22 en futuras.

### H-06 · Cifras de marketing 🟢
- Las cifras de escala de ezaudita no se usan para dimensionar; solo como evidencia de que el modelo de negocio existe. Sin acción.

### H-07 · Dimensionamiento de referencia 🟡
- El límite estándar de mercado (1M CFDI/RFC, tope 3M en alto volumen) sirve como objetivo de dimensionamiento del índice `comprobantes` y sus índices SQL. Se registra como RNF de escalabilidad.

### H-08 · D1/D2 heredadas 🟡
- Nomenclatura (UUID vs folio) y comprobante (registro vs PDF) siguen pendientes de Pedro. Ya mitigadas por diseño: plantilla configurable y bandera de PDF. No bloquean MVP; bloquean sus defaults.

---

## 3. Contenido sensible

Las fuentes no contienen credenciales, FIEL, RFC reales de clientes ni PII. Los datos de ezaudita (precios, contactos corporativos) son públicos. ✅ Sin acciones.

> Regla permanente: ningún documento del proyecto transcribe material de e.firma, contraseñas ni CFDI reales. Ejemplos con RFC de prueba del SAT (`EKU9003173C9`, `XAXX010101000`) y UUID ficticios.

---

## 4. Veredicto

| Criterio | Estado |
|---|---|
| Fuentes libres de contenido sensible | ✅ |
| Sin contradicciones bloqueantes | ✅ |
| Riesgos críticos identificados y ruteados (H-02 → ADR-003/doc 04/Sprint 1) | ✅ |
| Funciones de riesgo faseadas fuera del MVP (H-01, H-03, H-04) | ✅ |
| Supuesto de operación registrado (H-05: interna hasta que D4 diga lo contrario) | ✅ |
| **Fase 0 v2.0 puede iniciar** | ✅ |
