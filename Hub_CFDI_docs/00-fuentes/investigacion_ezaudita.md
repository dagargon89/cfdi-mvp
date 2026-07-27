# Investigación — Plataforma ezaudita® (ezaudita.com)

> **Documento fuente** entregado por David el 2026-07-27 como referencia funcional para el pivote del Hub CFDI a plataforma web. Se conserva el inventario funcional y los datos técnicos relevantes; se omiten secciones comerciales sin impacto de diseño (testimonios, redes sociales, datos societarios). La fuente completa está en el historial de la sesión. **No se edita**; el análisis vive en [`inventario_funcional.md`](inventario_funcional.md).

## Qué es ezaudita®

Plataforma web (SaaS) mexicana de **cumplimiento fiscal** — no de auditorías de campo/ISO. Automatiza la descarga masiva de CFDI/XML del SAT, calcula IVA e ISR, concilia con los visores del SAT, vigila la lista de EFOS (art. 69-B CFF) y genera la DIOT. Dirigida a contadores, empresas y despachos contables en México. Valor central: "tener la misma información que el SAT" — sincroniza diariamente vía web service del SAT los CFDI emitidos y recibidos (ejercicio actual + 5 anteriores), actualiza estatus vigente/cancelado con el metadata, y notifica por correo errores, cancelaciones tardías y operaciones con EFOS. Reporta 2,900 millones de CFDI procesados y 90,000 empresas usuarias (cifras de marketing propias, no verificadas).

100% web (app.ezaudita.com, sin app móvil nativa), corre en AWS, desarrollada por SICONT MEX S.A. de C.V. / SolucionCP (Zapopan, Jalisco). **La e.firma del SAT se resguarda en sus servidores.** Sin API pública, webhooks ni SSO documentados. Única integración: ADD de CONTPAQi® Contabilidad (complemento de pago, requiere instalación).

## Inventario funcional

### A. Sincronización y descarga de CFDI
1. **Sincronización automática con el SAT** — descarga diaria automática de todos los CFDI emitidos y recibidos vía web service, incluyendo metadata; actualiza estatus vigente/cancelado de toda la historia. Requiere e.firma/credenciales del SAT. Ejercicio actual + 5 anteriores.
2. **Descarga masiva manual** — bajo demanda del mes en curso ("Descarga manual" en Configuración/Avanzada/SAT Sync).
3. **Estatus de conexión con el SAT** — monitoreo del estado de conexión y avance de descargas.
4. **Visualización ilimitada de CFDI** — todos los tipos: Ingreso, Egreso, Traslado, Nómina y Pago.

### B. Organización, búsqueda y clasificación
5. **Listados con vistas configurables** — por ejercicio, periodo y tipo; columnas personalizables, búsquedas avanzadas y filtros.
6. **Localización de CFDI cancelados** — filtros dedicados.
7. **Moneda extranjera** — importes en divisa (vía "editar columnas").

### C. Cálculo de impuestos
8. **Cálculo automático de IVA (CFDI 4.0)** — IVA trasladado efectivamente cobrado e IVA acreditable efectivamente pagado por periodo, "mismo algoritmo que los visores del SAT": facturas de contado (PUE), complemento de pagos 2.0 (PPD) y retenciones. IVA a pagar o a favor del mes.
9. **Conciliación del precargado de IVA del SAT** — detecta CFDI incluidos y **excluidos** por el SAT en el prellenado de pagos provisionales/definitivos.
10. **ISR con base en flujo de efectivo** — ingresos acumulables y retenciones a flujo, control de deducciones, desglose y ajuste de periodos de acumulación.

### D. Complemento de pagos (REP)
11. **Conciliación de CFDI con complemento de pago** — saldo de cada factura PPD con base en los CFDI de pago relacionados; identifica pagos **pendientes de emitir o recibir**.

### E. Validaciones, riesgo y notificaciones
12. **Notificación de errores en CFDI** — valida errores comunes de emisión conforme a guías de llenado CFDI 4.0 (regla 2.7.1.32 RMF, 29-A CFF); avisa por correo.
13. **Validación de vigencia** — comprobación automática y detección de cancelaciones.
14. **Alerta de cancelaciones tardías** — cancelaciones en el mes en curso de CFDI de meses anteriores (principal causa de diferencias con lo declarado).
15. **Control de EFOS (art. 69-B CFF)** — cruce diario de la lista negra del SAT contra proveedores y facturas recibidas de toda la historia; notifica coincidencias.
16. **Notificaciones configurables** — correos ilimitados (aunque no sean usuarios registrados) para alertas de errores, EFOS y cancelaciones.

### F. Nómina
17. **Reportes de CFDI de nómina** — información para entero de retenciones y declaración de sueldos y salarios; visualización restringible por usuario.

### G. DIOT
18. **Generación y validación de la DIOT** — a partir de los CFDI recibidos, alimenta el archivo .txt de carga batch, alineada con datos del SAT.

### H. Documentos oficiales del SAT
19. **Descarga de CSF y Opinión de Cumplimiento** — PDF desde los servicios del SAT, con fecha de descarga y opción de actualizar (desde oct-2024).

### I. Dashboards, reportes y exportación
20. **Tablero de inicio** — ingresos, gastos, IVA y posibles errores de un vistazo.
21. **Dashboards estadísticos de CFDI.**
22. **Exportación XML / PDF / Excel** — desde listados, con filtros y selección; sin restricciones en planes de pago.

### J. Integración contable
23. **Sincronizador ADD de CONTPAQi® Contabilidad** (complemento de pago) — concilia cantidad de CFDI y estatus contra el ADD; envía faltantes; actualiza cancelados. Solo CONTPAQi®.

### K. Usuarios y multiempresa
24. **Multiusuario y multiempresa (multi-RFC)** — permisos por usuario para acceder/restringir empresas y CFDI de nómina.
25. **Gestión de suscripción y contraseña.**

## Planes y precios (referencia de mercado, MXN anuales con IVA, publicados a 2026-05-18)

| Plan | Lista / descuento | RFC | Usuarios |
|---|---|---|---|
| Gratis (10 días) | $0 | 1 | 1 |
| PYME | $4,290 / $3,432 | 1 | 1 |
| Empresarial | $5,990 / $4,792 | 3 | 1 |
| Corporativo | $10,390 / $8,312 | 10 | 3 |
| Despachos | $15,690 / $12,552 | Ilimitados | 5 |

Complementos: usuarios adicionales $1,990/$1,592; Sincronizador ADD $3,990/$3,192; alto volumen $16,990/$13,592 (RFC > 1M CFDI, tope 3M). Límite estándar: 1,000,000 CFDI por RFC.

## Caveats de la fuente

- Cifras de escala son marketing propio, no verificadas.
- La conciliación con el precargado/visores del SAT (función 9) no documenta su mecanismo técnico; no existe WS oficial público conocido para el prellenado.
- Sin API pública, webhooks, SSO ni app móvil: no son referencia de paridad.
