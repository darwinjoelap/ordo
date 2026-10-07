// Ordo PWA: registro del service worker, aviso de instalación y estado de conexión.
(function () {
  'use strict';
  const CLAVE = 'ordo.instalar.descartado';
  const DIAS = 30;

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {});
    });
  }

  const standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  if (standalone) document.documentElement.classList.add('ordo-instalada');

  // PDF dentro de la app instalada: abrirlos directo saca de la app y "atrás" la cierra.
  // Los enlaces/formularios con data-pdf se muestran en el visor interno (/visor/), que sí vuelve con "atrás".
  if (standalone) {
    const visor = function (href) {
      const u = new URL(href, location.href);
      return u.origin === location.origin ? '/visor/?u=' + encodeURIComponent(u.pathname + u.search) : null;
    };
    document.addEventListener('click', function (e) {
      const a = e.target.closest('a[data-pdf]');
      const destino = a && visor(a.href);
      if (destino) { e.preventDefault(); location.href = destino; }
    });
    document.addEventListener('submit', function (e) {
      const f = e.target;
      if (!f.matches || !f.matches('form[data-pdf]') || (f.method || 'get').toLowerCase() !== 'get') return;
      const destino = visor(f.action.split('?')[0] + '?' + new URLSearchParams(new FormData(f)).toString());
      if (destino) { e.preventDefault(); location.href = destino; }
    });
  }

  // Consulta sin conexión: mientras se usa Ordo con internet se refrescan, en segundo plano, la pantalla y los
  // datos de «Consulta rápida» (el service worker guarda la última respuesta). Como mucho cada 10 minutos.
  window.addEventListener('load', function () {
    if (!document.body.dataset.ordoConsulta || !navigator.onLine || !('serviceWorker' in navigator)) return;
    if (location.pathname.indexOf('/consulta/') === 0) return;
    try {
      const ultima = parseInt(sessionStorage.getItem('ordo.consulta.t') || '0', 10);
      if (Date.now() - ultima < 10 * 60 * 1000) return;
      sessionStorage.setItem('ordo.consulta.t', String(Date.now()));
    } catch (e) {}
    navigator.serviceWorker.ready.then(function () {
      fetch('/consulta/', { credentials: 'same-origin', cache: 'reload' }).catch(function () {});
      fetch('/consulta/datos.json?red=1', { credentials: 'same-origin' }).catch(function () {});
    });
  });
  // Al cerrar sesión se borra lo guardado para la consulta sin conexión en este dispositivo
  document.addEventListener('submit', function (e) {
    if (e.target.matches && e.target.matches('form[action$="/cuenta/salir/"]') && window.caches) {
      caches.delete('consulta-ordo');
      try { sessionStorage.removeItem('ordo.consulta.t'); } catch (x) {}
    }
  });

  function descartadoReciente() {
    try {
      const t = parseInt(localStorage.getItem(CLAVE) || '0', 10);
      return t && (Date.now() - t) < DIAS * 864e5;
    } catch (e) { return false; }
  }
  function descartar() {
    try { localStorage.setItem(CLAVE, String(Date.now())); } catch (e) {}
    const b = document.getElementById('ordo-instalar'); if (b) b.hidden = true;
  }

  function mostrar(modo) {
    const b = document.getElementById('ordo-instalar');
    if (!b || standalone || descartadoReciente()) return;
    b.querySelectorAll('[data-modo]').forEach(function (el) { el.hidden = el.dataset.modo !== modo; });
    b.hidden = false;
  }

  // Android / Chrome / Edge: prompt nativo
  let evento = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    evento = e;
    mostrar('nativo');
  });
  window.addEventListener('appinstalled', descartar);

  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-ordo-instalar]') && evento) {
      evento.prompt();
      evento.userChoice.finally(function () { evento = null; descartar(); });
    }
    if (e.target.closest('[data-ordo-descartar]')) descartar();
  });

  // iPhone / iPad (Safari): no hay prompt, se explica cómo hacerlo
  const ua = navigator.userAgent;
  const esIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const esSafari = /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
  if (esIOS && esSafari) window.addEventListener('load', function () { setTimeout(function () { mostrar('ios'); }, 1500); });

  // Estado de conexión
  function conexion() {
    const a = document.getElementById('ordo-sin-conexion');
    if (a) a.hidden = navigator.onLine;
  }
  window.addEventListener('online', conexion);
  window.addEventListener('offline', conexion);
  document.addEventListener('DOMContentLoaded', conexion);
})();
