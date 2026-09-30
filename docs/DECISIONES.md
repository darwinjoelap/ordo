# Decisiones de Ordo

| Fecha | Decisión | Motivo |
| --- | --- | --- |
| 2026-09-30 | Ordo desde cero en repo propio; BioLifeVentas solo como referencia | No poner en riesgo el sistema en producción |
| 2026-09-30 | Multiempresa con esquema compartido (campo `empresa`) | Simple, una sola BD en Railway |
| 2026-09-30 | Python 3.14 local y en Docker | Es la versión instalada en el equipo de desarrollo; Django 5.2 la soporta |
| 2026-09-30 | Login por correo; rol en la membresía usuario↔empresa | Un usuario puede tener roles distintos en varias empresas |
| 2026-09-30 | Bootstrap/HTMX servidos localmente | La PWA debe cargar sin depender de CDN |
| 2026-09-30 | Railway Pro con entornos staging y production | Logs de 30 días, soporte, respaldos |
