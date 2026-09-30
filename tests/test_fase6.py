"""
Pruebas de la Fase 6: PWA (manifest, service worker, página sin conexión).
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.empresas.models import Empresa, Membresia, Rol


class PWATests(TestCase):
    def test_manifest(self):
        r = self.client.get('/manifest.webmanifest')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/manifest+json')
        m = json.loads(r.content)
        self.assertEqual(m['display'], 'standalone')
        self.assertEqual(m['scope'], '/')
        tamanos = {(i['sizes'], i.get('purpose', 'any')) for i in m['icons']}
        self.assertIn(('192x192', 'any'), tamanos)
        self.assertIn(('512x512', 'any'), tamanos)
        self.assertIn(('512x512', 'maskable'), tamanos)

    def test_service_worker_en_la_raiz_y_sin_cache(self):
        r = self.client.get('/sw.js')
        self.assertEqual(r.status_code, 200)
        self.assertIn('javascript', r['Content-Type'])
        self.assertEqual(r['Service-Worker-Allowed'], '/')
        self.assertIn('no-cache', r['Cache-Control'])
        cuerpo = r.content.decode()
        self.assertIn('/offline/', cuerpo)
        self.assertNotIn('__PRECARGA__', cuerpo)
        # Las páginas nunca se guardan en caché (datos por empresa y usuario)
        self.assertIn("req.mode === 'navigate'", cuerpo)

    def test_offline_sin_sesion(self):
        r = self.client.get('/offline/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Sin conexión')

    def test_paginas_enlazan_manifest_y_registro(self):
        r = self.client.get('/cuenta/entrar/')
        self.assertContains(r, 'rel="manifest"')
        self.assertContains(r, 'js/pwa.js')
        u = get_user_model().objects.create_user('d@alfa.com', 'clave-segura-123')
        Membresia.objects.create(usuario=u, empresa=Empresa.objects.create(nombre='Alfa'), rol=Rol.DUENO)
        self.client.force_login(u)
        r = self.client.get('/')
        self.assertContains(r, 'rel="manifest"')
        self.assertContains(r, 'id="ordo-instalar"')

    def test_usuario_logueado_sin_empresa_tambien_obtiene_sw(self):
        u = get_user_model().objects.create_user('x@x.com', 'clave-segura-123')
        self.client.force_login(u)
        self.assertEqual(self.client.get('/sw.js').status_code, 200)
        self.assertEqual(self.client.get('/manifest.webmanifest').status_code, 200)

    def test_guia_de_instalacion(self):
        u = get_user_model().objects.create_user('g@alfa.com', 'clave-segura-123')
        Membresia.objects.create(usuario=u, empresa=Empresa.objects.create(nombre='Gamma'), rol=Rol.VENDEDOR)
        self.client.force_login(u)
        self.assertContains(self.client.get('/instalar/'), 'Agregar a inicio')
