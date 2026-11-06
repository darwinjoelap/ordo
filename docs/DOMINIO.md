# Dominio propio: una dirección por empresa

Cada empresa entra por **`https://<slug>.app.ordove.com/`**, igual que los consultorios de Ordo Salud
(`*.salud.ordove.com`). El código vive en `apps/core/subdominios.py`.

| Dirección | Qué es |
|---|---|
| `https://<slug>.app.ordove.com/` | Login con la marca de la empresa; al entrar trabaja sin ruta (`/ventas/`, `/inventario/`…) |
| `https://admin.app.ordove.com/` | Plataforma (superusuario) |
| `https://app.ordove.com/<slug>/` | Redirige al subdominio (solo si se agrega también `app.ordove.com` en Railway) |
| `https://ordocore.up.railway.app/<slug>/` | Respaldo: la ruta sigue funcionando en cualquier host |

Reglas:
- En el subdominio de una empresa solo vale una cuenta de ESA empresa (o soporte de plataforma). `/plataforma/` y
  `/admin/` no existen ahí (404).
- **No** se define `SESSION_COOKIE_DOMAIN` ni `CSRF_COOKIE_DOMAIN`: cada subdominio guarda su propia sesión, así la
  sesión de una empresa nunca vale en otra.
- El slug ya es válido como subdominio (minúsculas, números y guiones; `RESERVADOS` incluye `admin`, `www`, `app`…).
- Sin `BASE_DOMAIN` (desarrollo, o antes de configurar el dominio) todo funciona por ruta como antes.

## Puesta en marcha

### 1. Railway (production → web → Settings → Networking → Custom Domain)
- [ ] Agregar `*.app.ordove.com` (comodín: cubre todas las empresas y `admin.`).
- [ ] Opcional: `app.ordove.com` (solo para que `app.ordove.com/<slug>/` redirija).
- [ ] Anotar los registros que pide Railway: el CNAME del comodín y el/los de verificación `_acme-challenge`.

### 2. Cloudflare (zona `ordove.com`)
- [ ] Crear los registros **exactamente** como los da Railway, con la nube en **gris (DNS only)**. Con la nube naranja
  el certificado comodín no se emite.
- [ ] Esperar a que Railway marque el dominio como verificado y con certificado.

### 3. Variables del servicio web (al guardar, redespliega)
| Variable | Valor |
|---|---|
| `BASE_DOMAIN` | `app.ordove.com` |
| `ALLOWED_HOSTS` | `.app.ordove.com,ordocore.up.railway.app,healthcheck.railway.app` (+ lo que ya tenga) |
| `CSRF_TRUSTED_ORIGINS` | `https://*.app.ordove.com,https://ordocore.up.railway.app` |

El punto inicial de `.app.ordove.com` en `ALLOWED_HOSTS` cubre todos los subdominios.

### 4. Comprobar
- [ ] `https://admin.app.ordove.com/` → login de plataforma; el panel muestra el enlace nuevo de cada empresa.
- [ ] `https://<slug>.app.ordove.com/` → login con la marca; entrar y guardar un presupuesto (sin error CSRF).
- [ ] `https://<slug>.app.ordove.com/plataforma/` → 404.
- [ ] La dirección vieja `ordocore.up.railway.app/<slug>/` sigue funcionando.

### 5. Clientes
- [ ] Pasar a cada empresa su enlace nuevo (Plataforma → empresa → Enlace).
- [ ] En el teléfono: desinstalar la app instalada con la dirección vieja e instalarla desde el subdominio nuevo
  (cada dirección guarda su propia app, sesión y caché sin conexión).

## Cuenta de soporte Ordo
Una sola cuenta de plataforma (`es_soporte=True`, sin empresa, no superusuario) que entra por el login de
CUALQUIER empresa (`<slug>.app.ordove.com` o `/<slug>/`) en «Modo soporte»: permisos de Dueño, sin membresía, así
que no sale en Equipo, vendedores ni cuenta en el límite de usuarios. No entra a `/plataforma/` ni a `/admin/`.

- Crear o cambiar la contraseña (Railway → web → Shell): `python manage.py crear_soporte` (la pide dos veces; nunca
  va en código ni archivos). Desactivar: `python manage.py crear_soporte --desactivar`.
- Si la empresa tiene un usuario propio con el mismo nombre, gana el de la empresa; por eso `soporte`, `ordo`,
  `admin` y los nombres de cuentas de plataforma están reservados al agregar personas al equipo.
- Empresa suspendida: el login se abre con `?soporte=1` (el botón Entrar del panel ya lo agrega).
- Cada entrada queda en el log: `Soporte: <usuario> entró a la empresa ...`.
- Con subdominios, el botón «Entrar» del panel lleva al login de la empresa (cada subdominio tiene su sesión);
  el superusuario entra ahí con su misma cuenta.
