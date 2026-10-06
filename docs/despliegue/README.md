# Despliegue de Hub CFDI en un VPS

Guía para poner Hub CFDI en producción en un servidor propio. Todo corre en Docker en una sola
máquina: base de datos, cola, API, worker, programador de tareas y un proxy (Caddy) que sirve la
interfaz y obtiene el certificado TLS solo.

Lo que **todavía no está completo** está marcado en rojo, aquí y dentro de la propia aplicación.
No lo ocultes al presentar el sistema: cada bloque dice qué falta y qué riesgo se asume.

## Qué hay en el repositorio para desplegar

| Archivo | Para qué |
|---|---|
| `docker-compose.prod.yml` | Los siete servicios de producción. MySQL y Redis sin puertos al exterior |
| `deploy/hub.sh` | Envoltorio de `docker compose`: siempre el archivo y las variables correctas |
| `deploy/generar_secretos.sh` | Crea la KEK, las contraseñas y `.env.production` la primera vez. Nunca sobrescribe |
| `deploy/Caddyfile` | Proxy: TLS automático, HSTS, cabeceras de seguridad, API bajo `/v1` |
| `apps/web/Dockerfile` | Construye la interfaz y la sirve con Caddy |
| `deploy/respaldar.sh` | Respaldo cifrado (base + XML) con rotación |
| `deploy/ensayar_restauracion.sh` | Prueba que un respaldo se puede restaurar, sin tocar producción |
| `deploy/restaurar.sh` | Restauración real, con confirmación |
| `.env.production.example` | Plantilla de variables |
| `app/scripts/privilegios_mysql.py` | Deja a la app con un usuario de MySQL de privilegios mínimos |

## 1. Requisitos

- **Servidor:** Ubuntu 22.04 o 24.04 LTS. Mínimo 2 vCPU, 4 GB de RAM y 40 GB de disco. Los XML
  crecen con el tiempo: vigila el disco.
- **Docker Engine con el plugin de Compose** (instrucciones oficiales:
  <https://docs.docker.com/engine/install/ubuntu/>).
- **Un dominio** con un registro `A` apuntando a la IP del VPS. Sin esto Caddy no puede obtener
  el certificado.
- **Puertos abiertos:** 22 (SSH), 80 y 443. El 80 hace falta aunque todo se sirva por HTTPS: ahí
  responde el desafío de Let's Encrypt y desde ahí se redirige a HTTPS. MySQL y Redis **no** se
  publican.

## 2. Antes de tocar el servidor: Firebase

1. **Agrega tu dominio a Firebase.** Consola de Firebase → Authentication → Settings →
   *Authorized domains* → *Add domain*. Si te lo saltas, el login falla con
   `auth/unauthorized-domain` y la pantalla no explica por qué.
2. **Ten a mano la cuenta de servicio** (el `.json`). Puedes reutilizar la de desarrollo
   (`secrets/firebase-service-account.json`) o generar una nueva en Configuración del proyecto →
   Cuentas de servicio → *Generar nueva clave privada*.
3. **Ten a mano la configuración web** (Configuración del proyecto → Tus apps): `apiKey`,
   `authDomain`, `projectId`, `appId`, `messagingSenderId`, `storageBucket`.

## 3. Preparar el servidor

```bash
# Cortafuegos: solo SSH y web.
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable

# El código.
sudo git clone <url-del-repositorio> /opt/hub-cfdi
cd /opt/hub-cfdi

# Secretos: KEK, contraseñas, .env.production y la frase de los respaldos.
sudo deploy/generar_secretos.sh

# La cuenta de servicio de Firebase (uid 1000 = el usuario de la app dentro de la imagen).
sudo install -m 600 -o 1000 -g 1000 /ruta/a/cuenta-de-servicio.json secrets/firebase-service-account.json

# Completa lo marcado [TÚ]: DOMAIN, ACME_EMAIL, FIREBASE_PROJECT_ID y las VITE_FIREBASE_*.
sudo nano .env.production
```

**Antes de seguir, copia fuera del servidor** (gestor de contraseñas o medio offline):

- `secrets/kek.bin` — sin ella, las e.firmas de la bóveda no se pueden recuperar nunca.
- `/etc/hub-cfdi/respaldo.pass` — sin ella, los respaldos cifrados son ilegibles.

Y **nunca** guardes la KEK en el mismo lugar que los respaldos: con las dos juntas, el cifrado de
la bóveda no protege de nada.

## 4. Desplegar

```bash
sudo deploy/hub.sh up -d --build
sudo deploy/hub.sh ps
```

Lo que debes ver:

- `migrate` en **Exited (0)**: corrió las migraciones y aplicó los privilegios. Si salió con otro
  código: `sudo deploy/hub.sh logs migrate`.
- `api` en **healthy**; `mysql`, `redis`, `worker`, `beat` y `web` en **Up**.
- `https://TU-DOMINIO/health` responde `{"status":"ok"}` y `https://TU-DOMINIO` abre el login.

La primera vez, Caddy tarda unos segundos en obtener el certificado.

## 5. Primer administrador

1. Abre `https://TU-DOMINIO/bootstrap` e ingresa el `BOOTSTRAP_ADMIN_TOKEN` de `.env.production`.
2. Cuando entres como administrador, **borra el valor** de `BOOTSTRAP_ADMIN_TOKEN` en
   `.env.production` y aplica el cambio: `sudo deploy/hub.sh up -d api`.

El alta de arranque se cierra sola en cuanto existe un usuario, pero no hay razón para dejar el
token vivo.

## 6. Carga inicial

```bash
# Valores fiscales de partida (quedan PROPUESTOS; se confirman desde la pantalla).
sudo deploy/hub.sh exec api python -m app.scripts.cargar_configuracion_fiscal config/fiscal/param_fiscal.yaml
sudo deploy/hub.sh exec api python -m app.scripts.cargar_configuracion_fiscal config/fiscal/catalogo_percepcion.yaml
sudo deploy/hub.sh exec api python -m app.scripts.cargar_configuracion_fiscal config/fiscal/tabla_vacaciones.yaml
```

Después, desde la interfaz: crea la empresa, sube su e.firma, confirma los valores fiscales en
Configuración → Fiscal y activa la sincronización diaria en Config · Bitácora. La lista 69-B se
descarga sola a la 1:30 de la madrugada.

### ¿Empezar de cero o llevarse los datos de desarrollo?

**Recomendado: de cero.** La KEK de producción es nueva, así que las e.firmas cifradas con la de
desarrollo no se podrían abrir; se vuelven a subir. Los CFDI se vuelven a descargar con la
sincronización y una descarga manual del periodo histórico.

Si de verdad necesitas llevarte la base de desarrollo, tienes que llevarte **también la KEK de
desarrollo** (`secrets/kek.dev.bin`, renombrada a `kek.bin`) y restaurar con `deploy/restaurar.sh`
un respaldo hecho en desarrollo. Hazlo antes de subir cualquier e.firma nueva.

## 7. Respaldos

```bash
# Respaldo manual.
sudo deploy/respaldar.sh /var/backups/hub-cfdi

# Ensayo de restauración: restaura en una base aparte y compara tabla por tabla.
sudo deploy/ensayar_restauracion.sh /var/backups/hub-cfdi/hub-cfdi-AAAAMMDDTHHMMSSZ.tar.gz.gpg
```

Programado cada noche a las 3:30, con ensayo los domingos (`sudo crontab -e`):

```cron
30 3 * * *  cd /opt/hub-cfdi && deploy/respaldar.sh /var/backups/hub-cfdi >> /var/log/hub-cfdi-respaldo.log 2>&1
45 3 * * 0  cd /opt/hub-cfdi && deploy/ensayar_restauracion.sh "$(ls -1t /var/backups/hub-cfdi/*.gpg | head -1)" >> /var/log/hub-cfdi-respaldo.log 2>&1
```

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — copia de los respaldos fuera del servidor.** Los scripts dejan los
> respaldos en el mismo disco que los datos; si se pierde el VPS, se pierden los dos. Falta decidir
> el destino externo (otro servidor, almacenamiento de objetos, un disco en la oficina) y
> programar la copia. Hasta entonces, cópialos a mano con regularidad.

## 8. Operación

```bash
sudo deploy/hub.sh ps                          # estado
sudo deploy/hub.sh logs -f --tail=100 worker   # bitácora de un servicio
sudo git pull && sudo deploy/hub.sh up -d --build   # actualizar a una versión nueva
```

Actualizar con `up -d --build` vuelve a correr las migraciones (`migrate`) y reaplica los
privilegios de MySQL, así que una tabla nueva queda con sus permisos correctos sin pasos extra.

El worker no recarga código: `up -d --build` lo recrea, pero si cambias algo a mano,
`sudo deploy/hub.sh restart worker`.

## 9. Lo que NO está completo aún

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — prueba de carga.** Los requisitos piden listados en menos de 500 ms con
> un millón de comprobantes por empresa (runbook C.1/C.2). No hay datos sintéticos a esa escala ni
> arnés de carga; el sistema solo se ha probado con cientos de comprobantes.

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — filtro de secretos en los logs** (runbook A.8). No existe un filtro que
> borre tokens, contraseñas o material PEM de las bitácoras. El código evita registrarlos, pero no
> hay una red de seguridad si algún día se cuela uno.

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — `GET /v1/tareas/{id}` responde sin sesión.** Quien conozca el
> identificador de una tarea terminada obtiene su enlace de descarga sin iniciar sesión. Lo atenúan
> que el identificador no es adivinable y que el enlace caduca en 10 minutos. Arreglo de una línea,
> pendiente (auditoría del nivel 1, `docs/auditoria/nivel-1-acceso-e-identidad.md`).

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — doble solicitud al SAT.** Dos ejecuciones simultáneas del mismo job
> envían dos solicitudes, y el SAT rechaza la segunda dejando el job en error. Se alcanza con un
> doble clic en "Reintentar". Diseñado, no implementado (auditoría del nivel 3, prueba `N3-03`).

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — recuperación de jobs huérfanos.** Si un job se queda encolado sin
> ejecutarse (por ejemplo, un reinicio a media sincronización), nada lo retoma. La persistencia de
> Redis activada en producción reduce mucho el riesgo, pero no lo elimina.

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — rotación de la KEK.** No hay procedimiento para cambiar la llave maestra
> de la bóveda. Si se filtrara, habría que volver a cargar todas las e.firmas.

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — monitoreo.** Nada avisa si se llena el disco, si un contenedor queda
> caído o si el certificado no se renueva. Hoy hay que revisarlo a mano.

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — Content-Security-Policy.** El proxy envía HSTS, `nosniff`,
> `X-Frame-Options` y `Referrer-Policy`, pero no una CSP: el login de Firebase necesita varios
> orígenes de Google y una política mal hecha lo rompe. Falta diseñarla y probarla.

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — imagen de producción con herramientas de desarrollo.** `requirements.txt`
> es un congelado completo, así que la imagen trae pytest, mypy, testcontainers y el SDK de Docker,
> que en producción no se usan. No rompen nada, pero agrandan la imagen y la superficie de ataque.
> Falta separar las dependencias de ejecución de las de desarrollo.

> [!CAUTION]
> **NO ESTÁ COMPLETO AÚN — verificación final del runbook.** El runbook de Sprint 5
> (`Hub_CFDI_docs/06-pruebas/06b_verificacion_sprint5_produccion.md`) se corre **contra el servidor
> ya desplegado** y guarda evidencia de cada ítem. No se ha corrido.

Dentro de la aplicación, las secciones incompletas muestran una leyenda roja. La lista vive en un
solo archivo, `apps/web/src/lib/seccionesIncompletas.ts`: cuando una sección quede lista, se borra
su entrada y la leyenda desaparece.

## 10. Lo que ya se verificó (ensayo del 2026-10-06)

Antes de escribir esta guía, el stack de producción completo se levantó **desde una base vacía**
en una máquina local, con los mismos archivos de este repositorio y `DOMAIN=localhost`. Lo único
distinto del VPS real es el certificado (Caddy usa su propia CA para `localhost`).

| Comprobación | Resultado |
|---|---|
| `migrate` corre las 16 migraciones en una base vacía y aplica los privilegios | ✓ (37 tablas) |
| Los siete servicios arriba; `api` healthy | ✓ |
| HTTPS, redirección de HTTP, HSTS, `nosniff`, sin cabecera `Server` | ✓ |
| La interfaz se sirve, y las rutas profundas (`/e/11/comprobantes`) también | ✓ |
| La build habla con la API real (no quedó en modo demo) | ✓ |
| `/docs` y `/openapi.json` → 404; un endpoint de datos sin sesión → 401 | ✓ |
| MySQL y Redis sin puertos al exterior; solo `web` en 80/443 | ✓ |
| La app usa `hub_cfdi_app`: `UPDATE`/`DELETE` en `bitacora` y `CREATE TABLE` → `ERROR 1142` | ✓ |
| Tareas reales con el usuario restringido (lista 69-B: 14 055 filas borradas y reinsertadas) | ✓ |
| Carga de semillas fiscales con el usuario restringido | ✓ |
| `cryptography` 50 dentro de la imagen; la KEK no está horneada; corre como uid 1000 | ✓ |
| Respaldo cifrado (AES-256) sin la KEK dentro | ✓ |
| Ensayo de restauración: 37 de 37 tablas con las mismas filas | ✓ |
| Restauración real tras borrar datos y archivos: todo vuelve, la app sigue sana y con sus permisos | ✓ |

Tres defectos que el ensayo encontró y que ya están corregidos:

- **El healthcheck de MySQL mentía en el primer arranque** (se comprobaba por socket contra el
  servidor temporal de inicialización). El primer despliegue en el VPS habría fallado.
- **El ensayo de restauración daba verde comparando una sola tabla**: dentro del bucle,
  `docker compose exec` se comía la entrada estándar. Ahora además falla si compara menos tablas
  de las que existen.
- **`.env.production` y los respaldos no estaban en `.gitignore`**: un `git add .` en el
  servidor habría subido las contraseñas al repositorio.
