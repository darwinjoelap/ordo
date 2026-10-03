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

  function mostrarEstado() {
    var f = new Date(datos.generado);
    var cuando = f.toLocaleDateString('es-VE') + ' ' + f.toLocaleTimeString('es-VE', { hour: '2-digit', minute: '2-digit' });
    // Una respuesta recién traída del servidor tiene segundos; si es más vieja, vino de lo guardado en el dispositivo
    var viejo = (Date.now() - f.getTime()) > 90 * 1000;
    estado.className = 'alert py-2 small mb-2 ' + (viejo ? 'alert-warning' : 'alert-light border');
    estado.textContent = (viejo ? 'Sin conexión: datos guardados del ' : 'Datos actualizados: ') + cuando +
      (datos.tasa ? ' · Tasa ' + numero(datos.tasa.bs, 2) + ' Bs/USD (' + datos.tasa.fecha.split('-').reverse().join('/') + ')' : ' · Sin tasa');
    if (viejo) estado.textContent += '. La existencia y los precios pueden haber cambiado.';
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

  function cargar() {
    estado.className = 'alert alert-light border py-2 small mb-2'; estado.textContent = 'Cargando…';
    fetch(URL_DATOS, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok || (r.headers.get('Content-Type') || '').indexOf('json') === -1) throw new Error('sesion');
        return r.json();
      })
      .then(function (d) {
        datos = d;
        $('cq-empresa').textContent = d.empresa;
        $('cq-n-productos').textContent = d.productos.length;
        $('cq-n-clientes').textContent = d.clientes.length;
        $('cq-pestana-clientes').hidden = !d.clientes.length;
        mostrarEstado(); pintar();
      })
      .catch(function () {
        estado.className = 'alert alert-warning py-2 small mb-2';
        estado.textContent = navigator.onLine
          ? 'No se pudieron cargar los datos. Vuelve a entrar a Ordo e inténtalo de nuevo.'
          : 'Sin conexión y sin datos guardados en este dispositivo. Abre Ordo con internet al menos una vez.';
      });
  }

  buscar.addEventListener('input', pintar);
  $('cq-con-stock').addEventListener('change', pintar);
  $('cq-actualizar').addEventListener('click', cargar);
  document.querySelectorAll('[data-cq-vista]').forEach(function (b) {
    b.addEventListener('click', function () {
      vista = b.dataset.cqVista;
      document.querySelectorAll('[data-cq-vista]').forEach(function (x) { x.classList.toggle('active', x === b); });
      pintar();
    });
  });
  window.addEventListener('online', cargar);
  window.addEventListener('offline', function () { if (datos) mostrarEstado(); });
  cargar();
})();
