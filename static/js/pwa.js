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
