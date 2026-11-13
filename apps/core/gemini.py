"""
Cliente mínimo de Gemini (API REST, sin SDK), adaptado del de Ordo Salud.

- `store: false`: Google no guarda la conversación. Las fotos y PDF van en la misma petición (inline) y no se
  guardan en Ordo ni en Google.
- Dos intentos si Google está saturado; si el modelo no admite `thinking_config` o `response_json_schema`, se
  reintenta sin ellos.
- Sin clave o con IA_MODO='prueba' → `en_prueba()` es True y quien llama decide qué hacer sin salir a internet.
"""
import base64
import json
import time
from dataclasses import dataclass

import requests
from django.conf import settings

URL = 'https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent'
REINTENTABLES = (429, 500, 502, 503, 504)


class ErrorIA(Exception):
    pass


@dataclass
class Respuesta:
    datos: dict
    tokens_entrada: int = 0
    tokens_salida: int = 0
    modelo: str = ''


def en_prueba():
    return getattr(settings, 'IA_MODO', '') == 'prueba' or not getattr(settings, 'GEMINI_API_KEY', '')


def parte_archivo(contenido, tipo):
    return {'inline_data': {'mime_type': tipo, 'data': base64.b64encode(contenido).decode()}}


def parte_texto(texto):
    return {'text': texto}


def _sin_additional(esquema):
    if isinstance(esquema, dict):
        return {k: _sin_additional(v) for k, v in esquema.items() if k != 'additionalProperties'}
    if isinstance(esquema, list):
        return [_sin_additional(v) for v in esquema]
    return esquema


def _texto(datos):
    candidatos = datos.get('candidates') or []
    if not candidatos:
        motivo = (datos.get('promptFeedback') or {}).get('blockReason', 'sin respuesta')
        raise ErrorIA(f'La IA no devolvió resultado ({motivo}).')
    partes = (candidatos[0].get('content') or {}).get('parts') or []
    return ''.join(p.get('text', '') for p in partes if not p.get('thought'))


def _uso(datos):
    uso = datos.get('usageMetadata') or {}
    return uso.get('promptTokenCount', 0), uso.get('candidatesTokenCount', 0) + uso.get('thoughtsTokenCount', 0)


def _post(url, cuerpo, esquema, intentos=2):
    cabeceras = {'x-goog-api-key': settings.GEMINI_API_KEY, 'Content-Type': 'application/json'}
    ultimo = None
    for intento in range(intentos):
        try:
            r = requests.post(url, headers=cabeceras, data=json.dumps(cuerpo), timeout=settings.IA_TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as e:
            ultimo = e
            time.sleep(2)
            continue
        except requests.RequestException as e:
            raise ErrorIA(f'No se pudo conectar con la IA ({e.__class__.__name__}).') from e
        if r.status_code == 400:
            texto = r.text.lower()
            config = cuerpo['generation_config']
            if 'thinking' in texto and 'thinking_config' in config:
                config.pop('thinking_config')
                return _post(url, cuerpo, esquema, intentos)
            if 'schema' in texto and 'response_json_schema' in config:
                config.pop('response_json_schema')
                config['response_schema'] = _sin_additional(esquema)
                return _post(url, cuerpo, esquema, intentos)
        if r.status_code in REINTENTABLES and intento < intentos - 1:
            time.sleep(3)
            continue
        return r
    raise ErrorIA(f'La IA no respondió a tiempo ({ultimo.__class__.__name__}). Intenta de nuevo.') from ultimo


def json_estructurado(sistema, partes, esquema, modelo=None, temperatura=0.1):
    """Llama al modelo y devuelve Respuesta con `datos` = el JSON pedido (validado como dict)."""
    modelo = modelo or settings.IA_MODELO
    cuerpo = {
        'system_instruction': {'parts': [{'text': sistema}]},
        'contents': [{'role': 'user', 'parts': partes}],
        'generation_config': {'response_mime_type': 'application/json', 'response_json_schema': esquema,
                              'temperature': temperatura,
                              'thinking_config': {'thinking_level': settings.IA_RAZONAMIENTO}},
        'store': False,
    }
    r = _post(URL.format(modelo=modelo), cuerpo, esquema)
    if r.status_code != 200:
        raise ErrorIA(f'La IA no respondió bien ({r.status_code}). Intenta de nuevo en un momento.')
    datos = r.json()
    try:
        salida = json.loads(_texto(datos))
    except ValueError as e:
        raise ErrorIA('La IA devolvió un formato inesperado. Intenta de nuevo.') from e
    t_in, t_out = _uso(datos)
    return Respuesta(salida if isinstance(salida, dict) else {}, t_in, t_out, modelo)


def costo_usd(tokens_entrada, tokens_salida):
    return round((tokens_entrada * settings.IA_PRECIO_ENTRADA + tokens_salida * settings.IA_PRECIO_SALIDA) / 1e6, 6)
