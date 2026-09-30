FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Clave solo para poder ejecutar collectstatic en el build
RUN SECRET_KEY=solo-para-build python manage.py collectstatic --noinput

# Al arrancar: aplica migraciones pendientes y luego levanta gunicorn.
# (Respaldo del preDeployCommand de railway.json: si Railway no lo ejecuta, igual se migra.)
# Railway inyecta PORT; 8080 por defecto
CMD python manage.py migrate --noinput && gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-3} --threads 2 --timeout 60 --access-logfile - --error-logfile -
