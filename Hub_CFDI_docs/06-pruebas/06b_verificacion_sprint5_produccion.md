# Sprint 5 — Runbook de verificación (Endurecimiento y cierre de Fase 2)

> **Cuándo se ejecuta:** después de desplegar en el servidor de producción real. Casi todo el
> checklist de hardening solo es verificable de verdad contra el entorno desplegado (TLS, firewall,
> KEK en disco, `/docs` cerrado). Las verificaciones de contrato, OWASP y rendimiento se pueden
> ensayar antes en dev, pero el **gate de cierre** se corre contra producción.
>
> **Cómo se usa:** cada ítem tiene **Qué** (qué se comprueba), **Cómo** (pasos/comandos exactos),
> **Aprobación** (criterio objetivo de éxito) y **Evidencia** (qué guardar como prueba). Marca cada
> casilla solo cuando la evidencia esté guardada — DoD verificada, no declarada (Gobernanza v3 mejora 3).
>
> **Fuentes:** checklist de hardening doc 04 §4.2, respuesta a incidentes doc 04 §4.3, OWASP doc 04 §2,
> criterios de cierre MVP SRS §7, RNF-03/08 SRS §9, DDL doc 03.

## Convenciones

- **`$PROD`** = host de producción (por SSH). **`$APP`** = contenedor `api` (`docker compose exec api ...`).
- Comandos de test locales usan el venv del repo: `.venv/bin/python -m pytest ...` (los tests usan
  testcontainers; requieren Docker).
- Guarda toda la evidencia (salidas de comando, capturas, dumps) en una carpeta fechada, p. ej.
  `evidencia-cierre-fase2-YYYY-MM-DD/`, y referénciala en la tabla de sign-off al final.

---

## A. Checklist de hardening (doc 04 §4.2) — gate del lanzamiento

### A.1 — [ ] TLS activo con renovación automática; HSTS
- **Qué:** el sitio sirve solo por HTTPS con certificado válido, renovación automática, y cabecera HSTS.
- **Cómo:**
  1. `curl -sI https://<dominio>/ | grep -i strict-transport-security` → debe aparecer
     `Strict-Transport-Security: max-age=...; includeSubDomains`.
  2. `curl -sI http://<dominio>/` → debe redirigir a HTTPS (301/308 a `https://`).
  3. Verifica vigencia/emisor: `echo | openssl s_client -connect <dominio>:443 -servername <dominio> 2>/dev/null | openssl x509 -noout -dates -issuer`.
  4. Renovación automática: confirma el timer de certbot (`systemctl list-timers | grep certbot`) o el
     mecanismo del proxy (Caddy/Traefik lo hacen solo) y fuerza un dry-run (`certbot renew --dry-run`).
- **Aprobación:** HTTPS válido, HTTP redirige, HSTS presente, dry-run de renovación exitoso.
- **Evidencia:** salida de los 4 comandos.

### A.2 — [ ] Firewall: solo 443/22; MySQL/Redis internos
- **Qué:** desde fuera solo responden 443 (y 22 para SSH); MySQL (3306/3308) y Redis (6379/6380) NO
  son accesibles desde internet.
- **Cómo:**
  1. En `$PROD`: `sudo ufw status` (o `nft list ruleset`) → solo 22 y 443 permitidos.
  2. Desde una máquina EXTERNA: `nmap -Pn -p 22,443,3306,3308,6379,6380 <ip-publica>` → 22/443 `open`,
     el resto `filtered`/`closed`.
  3. Confirma que MySQL/Redis en `docker-compose.yml` NO publican puertos al host en producción (o solo a
     `127.0.0.1`). Los `3308:3306`/`6380:6379` que usa dev deben quitarse o bindearse a loopback en prod.
- **Aprobación:** el nmap externo solo muestra 22 y 443; BD/Redis no alcanzables desde fuera.
- **Evidencia:** `ufw status` + salida de `nmap` externo.

### A.3 — [ ] KEK con permisos 600, fuera de imagen, repo y backups de BD
- **Qué:** la Key Encryption Key (que descifra la bóveda de e.firmas) vive solo en el host con permisos
  `600`, y no está dentro de la imagen Docker, ni versionada, ni incluida en los backups de BD.
- **Cómo:**
  1. `ls -l <ruta-de-la-KEK>` → `-rw-------` (600), dueño = usuario de la app.
  2. `git log --all --full-history -- '*kek*' '*.key'` y `git grep -i "BEGIN.*KEY"` → sin resultados en el repo.
  3. `docker run --rm <imagen-api> sh -c 'ls -la / /app'` → la KEK NO está dentro de la imagen (se monta
     como secret/volumen en runtime, no se hornea).
  4. Verifica que el script de backup de BD (ver A.7) NO copie el archivo de la KEK ni su directorio.
- **Aprobación:** permisos 600, ausente del repo y de la imagen, excluida de backups.
- **Evidencia:** `ls -l` de la KEK + salida de los greps.

### A.4 — [ ] Usuario MySQL de la app con mínimos privilegios; `bitacora` INSERT-only
- **Qué:** el usuario que usa la app NO es root; tiene solo los privilegios que necesita; sobre la tabla
  `bitacora` solo puede INSERT (no UPDATE/DELETE — la bitácora es inmutable).
- **Cómo:** con el usuario de la app (no root):
  1. `docker compose exec mysql mysql -u<app_user> -p -e "SHOW GRANTS FOR CURRENT_USER();"` → revisar que
     NO haya `ALL PRIVILEGES` ni `GRANT OPTION`; que sea `SELECT, INSERT, UPDATE, DELETE` acotado al
     esquema `hub_cfdi`, y para `bitacora` solo `INSERT` (y `SELECT` si se lee).
  2. Prueba negativa: intentar `UPDATE bitacora SET ...` y `DELETE FROM bitacora ...` con el usuario de la
     app → deben fallar con error de permisos.
- **Aprobación:** grants mínimos; UPDATE/DELETE sobre `bitacora` rechazados.
- **Evidencia:** salida de `SHOW GRANTS` + los dos errores de permiso.

### A.5 — [ ] `pip-audit`/`npm audit` limpios; lockfiles con hashes
- **Qué:** sin vulnerabilidades conocidas sin mitigar en dependencias backend y frontend; instalaciones
  reproducibles con hashes.
- **Cómo:**
  1. Backend: `pip-audit --strict -r requirements.txt --ignore-vuln PYSEC-2026-286`
     (la excepción PYSEC-2026-286 está justificada en `Hub_CFDI_docs/CLAUDE.md:95` — SQLi vía dict keys
     manipuladas sin fix upstream, no aplica a nuestro uso; re-confirmar que sigue sin fix al cerrar).
  2. Frontend: `cd apps/web && npm audit --omit=dev` → sin vulnerabilidades `high`/`critical`.
  3. Reproducibilidad: `requirements.txt` con hashes (`--require-hashes` instalable) y `apps/web/package-lock.json` presente y commiteado.
- **Aprobación:** pip-audit sin hallazgos (salvo la excepción documentada), npm audit sin high/critical,
  lockfiles presentes.
- **Evidencia:** salidas de ambos audits.

### A.6 — [ ] `/docs` OpenAPI cerrado en producción
- **Qué:** el Swagger/OpenAPI (`/docs`, `/redoc`, `/openapi.json`) no está expuesto públicamente en prod.
- **Cómo:** `curl -so /dev/null -w "%{http_code}\n" https://<dominio>/docs` (y `/redoc`, `/openapi.json`)
  → 404 (o 401 si se protege con auth). Confirmar que la app arranca con la variable de entorno/ajuste que
  desactiva la doc en prod (FastAPI: `docs_url=None, redoc_url=None, openapi_url=None` cuando el entorno es
  producción). **Si aún no existe ese switch, hay que agregarlo antes de cerrar este ítem.**
- **Aprobación:** los tres endpoints devuelven 404/401 en producción.
- **Evidencia:** los tres códigos HTTP.

### A.7 — [ ] Backups cifrados + restore ensayado (incluye volumen de XML)
- **Qué:** existe un backup automático y **cifrado** de (a) la BD MySQL y (b) el volumen de XML/paquetes
  (`storage_root`), y se ha **ensayado un restore completo** en un entorno limpio.
- **Cómo:**
  1. **Construir primero** (no existe aún): un script de backup que haga `mysqldump` del esquema `hub_cfdi`
     + `tar` de `storage_root`, cifre la salida (p. ej. `age` o `gpg`, con clave FUERA del servidor de prod
     y distinta de la KEK), y lo suba a almacenamiento externo. Programarlo (cron/systemd timer) diario.
  2. **Ensayo de restore:** en una máquina/contenedor LIMPIO: descifrar el backup, `mysql < dump.sql`,
     restaurar `storage_root`, levantar `docker compose up -d`, y verificar que la app arranca, los
     comprobantes se listan y **un XML se puede abrir/descargar** (el volumen se restauró bien).
  3. Verifica que el backup NO contiene la KEK (cruza con A.3).
- **Aprobación:** backup cifrado se genera solo; restore en entorno limpio deja la app funcional con datos
  y XML intactos.
- **Evidencia:** script + log del cron, y captura/salida del ensayo de restore (app arriba, listado con
  datos, un XML abierto).

### A.8 — [ ] Filtro de redacción de secretos activo en logging
- **Qué:** los logs no filtran secretos (contraseñas de e.firma, KEK, tokens, contraseña SMTP, bearer tokens).
- **Cómo:**
  1. Revisar el filtro de logging en el código (buscar el `logging.Filter`/formatter de redacción).
  2. Prueba en vivo: disparar acciones que manejan secretos (alta de e.firma, guardar SMTP, login) y hacer
     `docker compose logs api worker beat | grep -iE "password|contrase|BEGIN .*KEY|Bearer |secret"` →
     no debe aparecer ningún secreto en claro (deben verse redactados, p. ej. `***`).
- **Aprobación:** ningún secreto en claro en los logs tras ejercitar los flujos sensibles.
- **Evidencia:** grep de logs mostrando redacción (y confirmación de que el filtro está registrado).

### A.9 — [ ] Pruebas negativas de A01/A02/A07 verdes contra el código final
- **Qué:** las pruebas de control de acceso (A01), criptografía/bóveda (A02) y autenticación (A07) pasan
  sobre el código que se va a producción. (Ver §D para el detalle por familia.)
- **Cómo:** `.venv/bin/python -m pytest tests/test_idor.py tests/test_auth.py tests/test_boveda.py tests/test_maquina_estados.py -v`
  sobre el commit desplegado.
- **Aprobación:** todas verdes; el commit probado == el desplegado (`git rev-parse HEAD`).
- **Evidencia:** salida de pytest + SHA del commit.

---

## B. Verificaciones de contrato

### B.1 — [ ] `ApiClient` (frontend) == endpoints reales del backend
- **Qué:** cada método del `ApiClient` congelado corresponde a un endpoint que existe en el OpenAPI real,
  con el mismo verbo, ruta y forma de request/response; y no hay endpoints huérfanos ni métodos muertos.
- **Cómo:**
  1. Exporta el OpenAPI real: `curl -s http://<api>/openapi.json > openapi.json` (o en dev antes de cerrar
     `/docs`).
  2. Lista los métodos del contrato en `apps/web/src/lib/api.ts` y su implementación en `api.http.ts`
     (rutas/verbos), y crúzalos 1:1 contra los `paths` del `openapi.json`.
  3. `cd apps/web && npm run typecheck` → el contrato tipa limpio contra su implementación.
- **Aprobación:** correspondencia 1:1 sin discrepancias de ruta/verbo/forma; typecheck limpio.
- **Evidencia:** tabla de cruce método↔endpoint + salida de typecheck.

### B.2 — [ ] Esquema real == DDL doc 03
- **Qué:** el esquema migrado en producción coincide con el modelo de datos documentado (doc 03): tablas,
  columnas, tipos, índices y restricciones `UNIQUE`/FK clave.
- **Cómo:**
  1. Volcar el esquema real: `docker compose exec mysql mysqldump --no-data hub_cfdi > schema_real.sql`.
  2. Comparar contra el DDL de `Hub_CFDI_docs/03-datos/03_modelo_de_datos.md` (tablas/columnas/índices,
     y en especial los `UNIQUE` que sostienen la idempotencia: `comprobantes(empresa_id,uuid)`,
     `lista_69b(rfc,version_lista)`, etc.).
  3. Confirmar que no hay migraciones pendientes (el arranque de la app no aplica cambios sorpresa).
- **Aprobación:** esquema real == DDL; sin drift; sin migraciones pendientes.
- **Evidencia:** `schema_real.sql` + notas del diff contra doc 03.

---

## C. Rendimiento y escalabilidad (RNF-03 / RNF-08)

### C.1 — [ ] RNF-03: listados < 500 ms p95 con 1M de comprobantes por empresa
- **Qué:** con el índice poblado a escala (1M CFDI en una empresa), los listados responden por debajo de
  500 ms en p95.
- **Cómo:**
  1. **Poblar** una empresa de prueba con ~1M comprobantes sintéticos (script de seed que inserte en
     `comprobantes` respetando el DDL e índices; NO usar el SAT). Aislar en una BD/entorno de prueba, no
     tocar datos reales.
  2. Prueba de carga sobre el endpoint de listado (`GET /v1/empresas/{id}/comprobantes` con filtros
     típicos: fechas, dirección, paginación) con una herramienta como `k6`/`wrk`/`hey`, midiendo p95.
  3. Repetir con los filtros más costosos (búsqueda `q`, cruce EFOS) para ver el peor caso.
- **Aprobación:** p95 < 500 ms en los listados clave con 1M de filas.
- **Evidencia:** reporte de la herramienta de carga (p50/p95/p99) + descripción del dataset.

### C.2 — [ ] RNF-08: el diseño soporta ≥ 50 empresas y 1M CFDI/empresa
- **Qué:** verificar (por diseño + medición puntual) que índices y workers escalan a ese volumen sin
  degradación grave; los workers son escalables horizontalmente.
- **Cómo:**
  1. Confirmar los índices de doc 03 presentes (cruza con B.2) y que las consultas de listado los usan
     (`EXPLAIN` sobre las queries clave → uso de índice, no full scan).
  2. Prueba de escala: varias empresas pobladas + varios jobs en cola en paralelo; observar que agregar
     réplicas de `worker` (`docker compose up -d --scale worker=N`) reparte la carga sin condiciones de
     carrera (la idempotencia por `UNIQUE(empresa_id,uuid)` lo protege).
- **Aprobación:** `EXPLAIN` usa índices; escalar workers aumenta throughput sin duplicar/corromper.
- **Evidencia:** salidas de `EXPLAIN` + observación del escalado de workers.

---

## D. Pruebas OWASP negativas (doc 04 §2) — detalle

Ejecutar sobre el commit desplegado. Estas son **pruebas negativas** (verifican que lo prohibido se
rechaza), no solo caminos felices.

### D.1 — [ ] A01 Broken Access Control (el riesgo #1)
- **Qué:** un usuario NO puede acceder a datos/acciones de una empresa sobre la que no tiene permiso;
  no hay enumeración de IDs (IDOR); los roles se respetan (CONSULTA no puede operar, etc.).
- **Cómo:** `.venv/bin/python -m pytest tests/test_idor.py tests/test_empresas.py -v` y, en vivo contra prod,
  intentar con un token de un usuario sin permiso: `GET /v1/empresas/{otra_empresa}/comprobantes`,
  `.../jobs`, `.../metadata` → 403/404 (nunca 200 con datos ajenos).
- **Aprobación:** todos los accesos cruzados devuelven 403/404; tests verdes.
- **Evidencia:** pytest + un par de intentos en vivo con su código HTTP.

### D.2 — [ ] A02 Cryptographic Failures (la bóveda)
- **Qué:** las e.firmas y la contraseña SMTP están cifradas en reposo (AES-256-GCM con sobre de KEK);
  sin la KEK los blobs no se descifran; los secretos nunca salen en respuestas de API.
- **Cómo:** `.venv/bin/python -m pytest tests/test_boveda.py -v`. En vivo: inspeccionar en BD que
  `efirmas`/`configuracion_smtp` guardan blobs cifrados (no texto claro), y que ningún endpoint devuelve
  la clave privada ni la contraseña SMTP.
- **Aprobación:** tests verdes; blobs cifrados en BD; sin secretos en respuestas.
- **Evidencia:** pytest + un `SELECT` mostrando el blob cifrado (no legible).

### D.3 — [ ] A07 Identification and Authentication Failures
- **Qué:** sin token válido no se entra; token vencido/manipulado se rechaza; usuario desactivado pierde
  acceso de inmediato (RF-AUTH-04); desfase de reloj tolerado según lo diseñado.
- **Cómo:** `.venv/bin/python -m pytest tests/test_auth.py -v`. En vivo: petición sin `Authorization` → 401;
  con token basura → 401; desactivar un usuario y confirmar que su siguiente petición falla.
- **Aprobación:** todos los caminos no autenticados/ inválidos rechazados; desactivación efectiva.
- **Evidencia:** pytest + intentos en vivo con su código HTTP.

---

## E. Criterios de cierre del MVP (SRS §7)

Marcar solo cuando A–D estén verdes y con evidencia.

- [ ] **§7.1 Prioridad 1:** login, permisos por empresa con negativos verificados (D.1), bóveda operando
  con cifrado y bitácora (D.2, A.4), e.firma vencida bloquea descargas.
- [ ] **§7.2 Prioridad 2:** ciclo asíncrono `solicitar→verificar→descargar` contra un RFC real vía workers,
  reanudación demostrada, comprobantes indexados y estatus validado.
- [ ] **§7.3 Prioridad 3:** sync diaria corriendo **≥ 1 semana sin intervención**, EFOS cruzado con alerta
  demostrada, cancelación tardía detectada y notificada, listados y export operando.
  *(Nota: el bug del `301` en sync se corrigió el 2026-07-29; la semana de corrida limpia debe contarse
  desde el entorno de producción estable.)*
- [ ] **§7.4 Checklist de cierre de Fase 2** (todo A–D) verificado ítem por ítem, incluyendo OWASP contra
  código final.

---

## F. Respuesta a incidentes (doc 04 §4.3) — tener listo antes del lanzamiento

No es una prueba, pero el runbook de incidentes debe estar accesible y entendido antes de abrir a
producción. Confirmar que el equipo sabe ejecutar:
1. **Compromiso del servidor o de la KEK:** aislar el servidor; asumir bóveda comprometida; notificar a
   cada empresa para **revocar y renovar su e.firma ante el SAT** (única remediación real); rotar KEK y
   credenciales; restaurar desde backup limpio (A.7); post-mortem en bitácora.
2. **Filtración de BD/backup sin KEK:** los blobs no son descifrables; evaluar exposición del índice de
   CFDI (datos fiscales) y notificar conforme LFPDPPP.
3. **Cuenta de usuario comprometida:** desactivar usuario (efecto inmediato, RF-AUTH-04), revisar su
   bitácora, rotar su acceso.

- [ ] Runbook de incidentes revisado y accesible; ensayo mental/tabletop hecho.

---

## Sign-off de cierre de Fase 2

| Sección | Ítems | Estado | Evidencia (carpeta/archivo) | Fecha | Responsable |
|---|---|---|---|---|---|
| A. Hardening | A.1–A.9 | ☐ | | | |
| B. Contrato | B.1–B.2 | ☐ | | | |
| C. Rendimiento | C.1–C.2 | ☐ | | | |
| D. OWASP negativas | D.1–D.3 | ☐ | | | |
| E. Cierre MVP (SRS §7) | §7.1–§7.4 | ☐ | | | |
| F. Incidentes | runbook | ☐ | | | |

**Fase 2 cerrada / MVP lanzado cuando todas las filas están ✅ con evidencia.**

---

### Piezas que hay que CONSTRUIR antes de poder verificar (no existen aún)
- **A.6** — switch para desactivar `/docs`/`/redoc`/`/openapi.json` en producción (si no está ya).
- **A.7** — script de backup cifrado (BD + `storage_root`) y su programación; procedimiento de restore.
- **C.1/C.2** — script de seed a escala (~1M comprobantes sintéticos) y arnés de prueba de carga (k6/wrk).
- El resto (A.1–A.5, A.8, A.9, B, D) es **verificación** de lo ya construido; no requiere código nuevo,
  salvo que alguna verificación descubra un hueco.
