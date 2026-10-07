// Consulta rápida: catálogo (precio y existencia) y clientes, solo lectura. Funciona sin conexión con lo
// último que guardó el service worker en este dispositivo.
(function () {
  'use strict';
  var URL_DATOS = document.currentScript.dataset.datos;
  var MAX = 150;
  var datos = null, vista = 'productos';
  var $ = function (id) { return document.getElementById(id); };
  var lista = $('cq-lista'), buscar = $('cq-buscar'), estado = $('cq-estado');

  function normal(t) { return (t || '').toString().normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function numero(n, dec) { return Number(n).toLocaleString('es-VE', { minimumFractionDigits: dec, maximumFractionDigits: dec }); }
  function el(tag, clase, texto) { var e = document.createElement(tag); if (clase) e.className = clase; if (texto != null) e.textContent = texto; return e; }

  var actualizando = false, fallo = false;
  function hace(ms) {
    var min = Math.floor(ms / 60000);
    if (min < 1) return 'hace un momento';
    if (min < 60) return 'hace ' + min + ' min';
    var h = Math.floor(min / 60);
    if (h < 24) return 'hace ' + h + ' h' + (min % 60 ? ' ' + (min % 60) + ' min' : '');
    var d = Math.floor(h / 24);
    return 'hace ' + d + (d === 1 ? ' día' : ' días');
  }
  // Aviso de antigüedad: verde = al día · amarillo = guardados hace rato · rojo = más de un día
  function mostrarEstado() {
    if (!datos) return;
    var f = new Date(datos.generado), edad = Date.now() - f.getTime();
    var cuando = f.toLocaleDateString('es-VE') + ' ' + f.toLocaleTimeString('es-VE', { hour: '2-digit', minute: '2-digit' });
    var nivel = edad < 5 * 60000 ? 'alert-success' : (edad < 24 * 3600000 ? 'alert-warning' : 'alert-danger');
    var texto = 'Datos de ' + hace(edad) + ' (' + cuando + ')';
    texto += datos.tasa ? ' · Tasa ' + numero(datos.tasa.bs, 2) + ' Bs/USD (' + datos.tasa.fecha.split('-').reverse().join('/') + ')' : ' · Sin tasa';
    if (actualizando) texto += ' · Actualizando…';
    else if (fallo) texto += navigator.onLine ? ' · No se pudo actualizar (señal débil). Toca ↻ para reintentar.' : ' · Sin conexión.';
    if (edad >= 5 * 60000 && !actualizando) texto += ' La existencia y los precios pueden haber cambiado.';
    estado.className = 'alert py-2 small mb-2 ' + nivel;
    estado.textContent = texto;
  }

  function filaProducto(p) {
    var a = el('div', 'list-group-item d-flex justify-content-between gap-2');
    var izq = el('div', 'min-w-0');
    izq.appendChild(el('div', 'fw-semibold', p.n));
    izq.appendChild(el('div', 'small text-muted', [p.c, p.m, p.g].filter(Boolean).join(' · ')));
    var st = p.d > 0 ? el('div', 'small', 'Disponible: ' + numero(p.d, 0) + ' ' + p.u) : el('div', 'small text-danger fw-bold', 'SIN STOCK');
    izq.appendChild(st);
    var der = el('div', 'text-end text-nowrap');
    der.appendChild(el('div', 'fw-bold', '$ ' + numero(p.p, 2)));
    if (datos.tasa) der.appendChild(el('div', 'small text-muted', 'Bs ' + numero(Math.round(p.p * datos.tasa.bs * 100) / 100, 2)));
    a.appendChild(izq); a.appendChild(der);
    return a;
  }
  function filaCliente(c) {
    var a = el('div', 'list-group-item');
    a.appendChild(el('div', 'fw-semibold', c.n));
    a.appendChild(el('div', 'small text-muted', [c.r, c.k].filter(Boolean).join(' · ')));
    if (c.t) { var t = el('a', 'small d-block', c.t); t.href = 'tel:' + c.t.replace(/[^\d+]/g, ''); a.appendChild(t); }
    if (c.d) a.appendChild(el('div', 'small text-muted', c.d));
    return a;
  }

  function pintar() {
    if (!datos) return;
    var q = normal(buscar.value).split(/\s+/).filter(Boolean);
    var soloStock = $('cq-con-stock').checked;
    var origen = vista === 'productos' ? datos.productos : datos.clientes;
    var filas = origen.filter(function (x) {
      if (vista === 'productos' && soloStock && x.d <= 0) return false;
      if (!x._t) x._t = normal(vista === 'productos' ? [x.n, x.c, x.m, x.g].join(' ') : [x.n, x.r, x.k, x.t].join(' '));
      return q.every(function (palabra) { return x._t.indexOf(palabra) !== -1; });
    });
    lista.textContent = '';
    filas.slice(0, MAX).forEach(function (x) { lista.appendChild(vista === 'productos' ? filaProducto(x) : filaCliente(x)); });
    if (!filas.length) lista.appendChild(el('div', 'list-group-item text-muted', 'Nada coincide con la búsqueda.'));
    $('cq-pie').textContent = filas.length > MAX ? 'Se muestran ' + MAX + ' de ' + filas.length + '. Escribe más para afinar.' : filas.length + ' resultado(s).';
    $('cq-filtro-stock').hidden = vista !== 'productos';
  }

  function leer(r) {
    if (!r.ok || r.redirected || (r.headers.get('Content-Type') || '').indexOf('json') === -1) throw new Error('sesion');
    return r.json();
  }
  function usar(d) {
    if (datos && new Date(d.generado) < new Date(datos.generado)) return;      // nunca retroceder
    datos = d;
    $('cq-empresa').textContent = d.empresa;
    $('cq-n-productos').textContent = d.productos.length;
    $('cq-n-clientes').textContent = d.clientes.length;
    $('cq-pestana-clientes').hidden = !d.clientes.length;
    mostrarEstado(); pintar();
  }
  // Ponerse al día con el servidor, sin bloquear: lo guardado ya está en pantalla. Se rinde a los 20 s.
  function actualizar() {
    if (actualizando) return;
    actualizando = true; mostrarEstado();
    var corte = window.AbortController ? new AbortController() : null;
    var reloj = setTimeout(function () { if (corte) corte.abort(); }, 20000);
    fetch(URL_DATOS + '?red=1', { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal: corte ? corte.signal : undefined })
      .then(leer)
      .then(function (d) { fallo = false; actualizando = false; usar(d); mostrarEstado(); })
      .catch(function () {
        fallo = true; actualizando = false;
        if (datos) { mostrarEstado(); return; }
        estado.className = 'alert alert-warning py-2 small mb-2';
        estado.textContent = navigator.onLine
          ? 'No se pudieron cargar los datos. Revisa la señal o vuelve a entrar a Ordo, y toca ↻.'
          : 'Sin conexión y sin datos guardados en este dispositivo. Abre Ordo con internet al menos una vez.';
      })
      .then(function () { clearTimeout(reloj); });
  }
  // Primero lo guardado en el dispositivo (instantáneo); después, la versión del servidor por detrás.
  function cargar() {
    if (!datos) { estado.className = 'alert alert-light border py-2 small mb-2'; estado.textContent = 'Cargando…'; }
    fetch(URL_DATOS, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(leer).then(usar).catch(function () {})
      .then(actualizar);
  }

  buscar.addEventListener('input', pintar);
  $('cq-con-stock').addEventListener('change', pintar);
  $('cq-actualizar').addEventListener('click', actualizar);
  document.querySelectorAll('[data-cq-vista]').forEach(function (b) {
    b.addEventListener('click', function () {
      vista = b.dataset.cqVista;
      document.querySelectorAll('[data-cq-vista]').forEach(function (x) { x.classList.toggle('active', x === b); });
      pintar();
    });
  });
  window.addEventListener('online', actualizar);
  window.addEventListener('offline', function () { fallo = true; mostrarEstado(); });
  setInterval(mostrarEstado, 30000);                       // la antigüedad avanza sola
  cargar();
})();
