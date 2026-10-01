# Despliegue de Ordo en Railway (staging)

Entorno `staging` ← rama `develop`. Producción (`main`) se arma igual en la Fase 7.
Los nombres de botones pueden variar un poco según la versión del panel de Railway.

## 0. Antes de empezar
- [ ] Railway en plan Pro (Account → Plans).
- [ ] Repo `darwinjoelap/ordo` con la rama `develop` al día (`git push`).
- [ ] Railway conectado a tu GitHub (Account → Integrations → GitHub) con acceso al repo `ordo`.
- [ ] Generar la SECRET_KEY de staging (PowerShell):
      `python -c "import secrets; print(secrets.token_urlsafe(50))"`  → guárdala, no la compartas.

## 1. Proyecto y entorno
1. Railway → **New Project → Empty Project**. Renómbralo **Ordo** (Settings del proyecto).
2. Arriba, selector de entorno (dice `production`) → **+ New Environment** → nombre `staging` → **Empty environment**.
3. Asegúrate de estar en `staging` para todo lo que sigue.

## 2. Base de datos
1. **+ Create → Database → PostgreSQL**. Queda un servicio llamado `Postgres`.
2. No actives "Public Networking"/TCP Proxy: Ordo se conecta por la red interna.

## 3. Servicio web
1. **+ Create → GitHub Repo → darwinjoelap/ordo**.
2. Renombra el servicio a **`web`** (clic en el nombre).
3. **Settings → Source → Branch**: `develop`. Activa auto-deploy.
4. **Settings → Networking → Generate Domain**. Si pide puerto: **8080**.
   Anota el dominio, ej. `web-staging-xxxx.up.railway.app`.
5. **Variables** (pestaña Variables → Raw Editor) — pega y ajusta:
   ```
   SECRET_KEY=<la clave generada en el paso 0>
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ALLOWED_HOSTS=${{RAILWAY_PUBLIC_DOMAIN}},healthcheck.railway.app
   CSRF_TRUSTED_ORIGINS=https://${{RAILWAY_PUBLIC_DOMAIN}}
   CLOUDINARY_CLOUD_NAME=<de tu cuenta Cloudinary>
   CLOUDINARY_API_KEY=<...>
   CLOUDINARY_API_SECRET=<...>
   SECURE_HSTS_SECONDS=3600
   ```
   - `healthcheck.railway.app` es obligatorio: es el host con el que Railway consulta `/salud/`.
   - Cloudinary: puedes usar la misma cuenta de BioLifeVentas; Ordo guarda todo bajo la carpeta `ordo/`.
   - Opcional: `SENTRY_DSN=<dsn del proyecto Ordo en Sentry>`.
6. **Deploy** (o "Apply changes"). El build usa el `Dockerfile`; antes de arrancar corre `migrate`
   (preDeployCommand de `railway.json`) y luego verifica `/salud/`.
7. Verificación: abre `https://<dominio>/salud/` → `{"estado": "ok"}`.

## 4. Primer usuario y empresa (Railway CLI)
Instala la CLI (requiere Node.js): `npm i -g @railway/cli`  → `railway login`.
```powershell
cd C:\proyectos\ordo
railway link            # elige proyecto Ordo, entorno staging, servicio web
railway ssh             # abre una consola DENTRO del servicio web
```
Dentro de la consola:
```bash
python manage.py createsuperuser                       # admin de plataforma (/admin/)
python manage.py crear_empresa "BioLife Diagnostics" darwin --enlace biolife --password "<clave>"   # o desde /plataforma/
python manage.py actualizar_tasa_bcv
exit
```
- El superusuario (plataforma) entra por la dirección principal; el Dueño de la empresa entra por `/<enlace>/` con su usuario.
- Si `actualizar_tasa_bcv` falla (el sitio del BCV a veces rechaza conexiones o tiene el certificado mal),
  carga la tasa a mano en `/admin/` → Tasas de cambio, y pásame el mensaje de error.

## 5. Servicio cron (tareas diarias)
1. **+ Create → GitHub Repo → darwinjoelap/ordo** otra vez. Renómbralo **`cron`**.
2. **Settings → Source → Branch**: `develop`.
3. **Settings → Config-as-code / Railway config file**: `/railway.cron.json`
   (define: comando `python manage.py tareas_programadas`, horario `0 11 * * *` = 7:00 a. m. Venezuela, sin healthcheck).
4. **Variables**:
   ```
   SECRET_KEY=${{web.SECRET_KEY}}
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ```
5. No le generes dominio. Deploy. En **Deployments → View logs** de cada ejecución debe verse
   `Apartados vencidos liberados: N` y `Tasa BCV registrada: ...`.

## 6. Probar la PWA en el teléfono
- **iPhone** (Safari): abre el dominio → Compartir → Agregar a inicio → abre desde el ícono.
- **Android** (Chrome): abre el dominio → aviso "Instala Ordo" → Instalar.
- Revisa: login, crear presupuesto, PDF, aviso "Sin conexión" (modo avión).

## 7. Checklist de cierre
- [ ] `/salud/` responde ok
- [ ] Login con el dueño y Mi empresa con logo (confirma que el logo queda en Cloudinary)
- [ ] Tasa BCV visible en la barra superior
- [ ] Cron ejecutado al menos una vez (se puede forzar con "Run now" si el panel lo ofrece)
- [ ] App instalada en iPhone y Android

## Seguridad pendiente: contraseña de Postgres de BioLifeVentas
La URL que se compartió en el chat era la **interna** (`*.railway.internal`), que solo funciona dentro de Railway.
1. En el proyecto BioLifeVentas → servicio Postgres → **Settings → Networking**:
   si **no** hay TCP Proxy / dominio público, la URL filtrada no sirve desde internet (riesgo bajo).
   Si hay TCP Proxy y no lo usas, elimínalo.
2. Para cambiar la clave sin cortar el servicio, sigue la guía oficial
   "Rotate API Keys and Database Credentials Without Downtime" (crea un rol nuevo, actualiza
   `PGUSER`/`PGPASSWORD` del servicio Postgres con `--skip-deploys`, redeploy de la app, luego borra el rol viejo).
   Hazlo en horario de poco uso y con un respaldo reciente de la base.
