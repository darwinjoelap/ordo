"""
Ordo — Settings de desarrollo local.
"""
from .base import *  # noqa: F401,F403
from .base import STORAGES

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# En local no hace falta collectstatic
STORAGES = {
    **STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# Django Debug Toolbar (pip install -r requirements-dev.txt)
try:
    import debug_toolbar  # noqa: F401
    INSTALLED_APPS += ['debug_toolbar']  # noqa: F405
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')  # noqa: F405
    INTERNAL_IPS = ['127.0.0.1']
    DEBUG_TOOLBAR = True
    DEBUG_TOOLBAR_CONFIG = {'SHOW_COLLAPSED': True}
except ImportError:
    DEBUG_TOOLBAR = False

# WhiteNoise en local: sirve desde static/ sin collectstatic y sin advertencias
from .base import STATIC_ROOT  # noqa: E402
STATIC_ROOT.mkdir(exist_ok=True)
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True
