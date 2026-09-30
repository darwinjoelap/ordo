"""
Ordo — Settings de producción y staging (Railway).
"""
from decouple import config

from .base import *  # noqa: F401,F403

DEBUG = False

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r'^salud/$']  # healthcheck interno de Railway
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=3600, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 días: la PWA no pide login a diario

# ── Sentry (solo si hay DSN) ──────────────────────────────────────────────────
SENTRY_DSN = config('SENTRY_DSN', default='')
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=config('RAILWAY_ENVIRONMENT_NAME', default='production'),
        release=ORDO_VERSION,  # noqa: F405
        traces_sample_rate=0.05,
        send_default_pii=False,
    )
