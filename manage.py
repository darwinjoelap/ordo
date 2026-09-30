#!/usr/bin/env python
"""Utilidad de línea de comandos de Django para Ordo."""
import os
import sys


def main():
    # Local: settings de desarrollo. Railway define DJANGO_SETTINGS_MODULE=config.settings.prod
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            'No se pudo importar Django. ¿Activaste el venv? '
            '(.\\venv\\Scripts\\Activate.ps1)'
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
