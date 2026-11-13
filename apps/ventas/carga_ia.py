"""
Cargar un presupuesto desde un pedido con IA (texto pegado, fotos o PDF). Método en dos pasos para gastar poco:

1. LEER: la IA solo transcribe el pedido a líneas {texto, código, cantidad, unidad}. No ve el inventario.
2. BUSCAR: Ordo busca candidatos en el inventario de la empresa (código exacto, o palabras del nombre/marca/código).
3. ELEGIR: solo para las líneas sin código exacto, la IA elige entre ESOS candidatos (no puede inventar productos).

El resultado se revisa en pantalla antes de agregar nada; se agrega con `servicios.agregar_item` (precios, rangos,
IVA y stock como siempre). El pedido no se guarda: pasa por memoria y se descarta.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from apps.core import gemini
from apps.inventario.models import Producto

MAX_ARCHIVOS = 5
MAX_BYTES_ARCHIVO = 8 * 1024 * 1024
MAX_BYTES_TOTAL = 15 * 1024 * 1024
MAX_TEXTO = 6000
MAX_LINEAS = 60
MAX_CANDIDATOS = 8
TIPOS = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif', 'application/pdf'}


class ErrorPedido(Exception):
    pass


@dataclass
class Linea:
    texto: str
    codigo: str = ''
    cantidad: int = 1
    unidad: str = ''
    nota: str = ''
    candidatos: list = field(default_factory=list)       # [Producto]
    producto: Producto | None = None
    confianza: str = ''                                    # exacto | alta | media | baja | ''


@dataclass
class Resultado:
    lineas: list
    tokens_entrada: int = 0
    tokens_salida: int = 0
    modelo: str = ''

    @property
    def sugeridas(self):
        return sum(1 for x in self.lineas if x.producto)


# ── Normalización y búsqueda local ───────────────────────────────────────────────────────────────────────────

def normalizar(texto):
    texto = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9%]+', ' ', texto).strip()


def _palabras(texto):
    return [p for p in normalizar(texto).split() if len(p) >= 2 or p.isdigit()]


class Catalogo:
    """El inventario activo de la empresa, normalizado una vez por pedido."""

    def __init__(self, productos):
        self.productos = list(productos)
        self.por_codigo = {normalizar(p.codigo).replace(' ', ''): p for p in self.productos if p.codigo}
        self.textos = [(p, f'{normalizar(p.codigo)} {normalizar(p.nombre)} '
                           f'{normalizar(p.marca.nombre if p.marca_id else "")} '
                           f'{normalizar(p.unidad.nombre if p.unidad_id else "")}') for p in self.productos]

    def exacto(self, *codigos):
        for codigo in codigos:
            clave = normalizar(codigo).replace(' ', '')
            if clave and clave in self.por_codigo:
                return self.por_codigo[clave]
        return None

    def candidatos(self, linea):
        palabras = _palabras(f'{linea.texto} {linea.codigo} {linea.unidad}')
        if not palabras:
            return []
        puntajes = []
        for producto, texto in self.textos:
            palabras_texto = texto.split()
            puntos = 0.0
            for p in palabras:
                if f' {p} ' in f' {texto} ':
                    puntos += 2 if len(p) >= 3 else 1
                elif len(p) >= 4 and any(w.startswith(p[:4]) for w in palabras_texto):
                    puntos += 1                      # «glifos» → glifosato, «fertiliz» → fertilizante
            if puntos:
                puntajes.append((puntos, producto.nombre, producto))
        puntajes.sort(key=lambda x: (-x[0], x[1]))
        return [p for _, _, p in puntajes[:MAX_CANDIDATOS]]


def catalogo(perfil):
    qs = Producto.objects.filter(activo=True).select_related('marca', 'unidad')
    if not perfil.maneja_servicios:
        qs = qs.fisicos()
    return Catalogo(qs)


# ── Paso 1: leer el pedido ───────────────────────────────────────────────────────────────────────────────────

LEER = """Lees pedidos que los clientes envían a una empresa venezolana que vende productos (insumos, reactivos,
agroquímicos, repuestos u otros). El pedido puede ser un mensaje de texto mal escrito, la foto de una lista escrita a
mano o una orden de compra (foto o PDF) con códigos y siglas.

Devuelve una línea por cada producto pedido:
- texto: el producto tal como aparece (siglas, marca, presentación, concentración), SIN la cantidad.
- codigo: si la línea trae un código o referencia de producto (columna Código, Ref., Cód.), cópialo exacto; si no, "".
- cantidad: unidades pedidas, solo la cifra (si no lo dice, 1).
- unidad: la presentación o unidad si aparece (saco, galón, litro, caja, kg, frasco…), si no "".

No incluyas precios, totales, datos del cliente, direcciones, firmas ni saludos. No inventes productos. Si una parte
no se lee bien, escribe lo que se lea y agrega "(?)" al final del texto."""

ESQUEMA_LEER = {'type': 'object', 'required': ['lineas'], 'properties': {
    'lineas': {'type': 'array', 'items': {'type': 'object', 'required': ['texto', 'cantidad'], 'properties': {
        'texto': {'type': 'string'}, 'codigo': {'type': 'string'}, 'cantidad': {'type': 'number'},
        'unidad': {'type': 'string'}}}}}}


def _cantidad(valor):
    """(cantidad entera ≥ 1, nota si se ajustó)."""
    try:
        numero = float(str(valor).replace(',', '.'))
    except (TypeError, ValueError):
        return 1, 'Cantidad no indicada: se puso 1.'
    if numero <= 0:
        return 1, 'Cantidad no indicada: se puso 1.'
    entero = max(1, round(numero))
    return entero, ('' if entero == numero else f'El pedido dice {valor}: se redondeó a {entero}.')


def _lineas_de(datos):
    lineas = []
    for d in (datos.get('lineas') or [])[:MAX_LINEAS]:
        if not isinstance(d, dict) or not str(d.get('texto') or '').strip():
            continue
        cantidad, nota = _cantidad(d.get('cantidad'))
        lineas.append(Linea(texto=str(d['texto']).strip()[:200], codigo=str(d.get('codigo') or '').strip()[:50],
                            cantidad=cantidad, unidad=str(d.get('unidad') or '').strip()[:40], nota=nota))
    return lineas


RE_LINEA_PRUEBA = re.compile(r'^\s*[-•*]?\s*(\d+(?:[.,]\d+)?)\s*(?:x\s+)?(.+)$', re.I)


def _leer_prueba(texto):
    """Modo de prueba (sin IA): una línea por renglón; un número al inicio es la cantidad."""
    lineas = []
    for renglon in texto.splitlines():
        renglon = renglon.strip()
        if not renglon:
            continue
        m = RE_LINEA_PRUEBA.match(renglon)
        cantidad, resto = (m.group(1), m.group(2)) if m else (1, renglon)
        n, nota = _cantidad(cantidad)
        lineas.append(Linea(texto=resto.strip()[:200], cantidad=n, nota=nota))
    return lineas[:MAX_LINEAS]


def leer(texto, archivos):
    """archivos: [(bytes, tipo)]. Devuelve (lineas, Respuesta | None)."""
    if gemini.en_prueba():
        if archivos:
            raise ErrorPedido('La IA no está configurada (modo de prueba): por ahora solo se puede pegar texto.')
        return _leer_prueba(texto), None
    partes = [gemini.parte_archivo(contenido, tipo) for contenido, tipo in archivos]
    if texto:
        partes.append(gemini.parte_texto(f'Mensaje del pedido:\n"""\n{texto}\n"""'))
    partes.append(gemini.parte_texto('Extrae las líneas del pedido.'))
    r = gemini.json_estructurado(LEER, partes, ESQUEMA_LEER, temperatura=0)
    return _lineas_de(r.datos), r


# ── Paso 3: elegir entre los candidatos ──────────────────────────────────────────────────────────────────────

ELEGIR = """Para cada línea de un pedido, elige el producto del inventario que corresponde, SOLO entre los candidatos
de esa línea (por su código). Usa siglas, abreviaturas, marca, presentación, concentración y unidad para decidir.
Si ninguno corresponde con seguridad razonable, devuelve codigo "".
confianza: "alta" si es claramente ese producto; "media" si es probable; "baja" si dudas."""

ESQUEMA_ELEGIR = {'type': 'object', 'required': ['elecciones'], 'properties': {
    'elecciones': {'type': 'array', 'items': {'type': 'object', 'required': ['linea', 'codigo', 'confianza'],
                                              'properties': {'linea': {'type': 'integer'}, 'codigo': {'type': 'string'},
                                                             'confianza': {'type': 'string',
                                                                           'enum': ['alta', 'media', 'baja']}}}}}}


def _describir(p):
    partes = [p.codigo, p.nombre]
    if p.marca_id:
        partes.append(f'marca {p.marca.nombre}')
    if p.unidad_id:
        partes.append(f'unidad {p.unidad.nombre}')
    return ' | '.join(partes)


def elegir(lineas):
    """Solo las líneas que tienen candidatos y no tienen código exacto. Devuelve Respuesta | None."""
    pendientes = [(i, x) for i, x in enumerate(lineas) if x.candidatos and not x.producto]
    if not pendientes:
        return None
    if gemini.en_prueba():
        for _, x in pendientes:                          # el más parecido según la búsqueda local
            x.producto, x.confianza = x.candidatos[0], 'baja'
        return None
    bloques = []
    for i, x in pendientes:
        detalle = f'{x.texto}' + (f' (código del pedido: {x.codigo})' if x.codigo else '') + \
                  (f' (unidad: {x.unidad})' if x.unidad else '')
        opciones = '\n'.join(f'   - {_describir(p)}' for p in x.candidatos)
        bloques.append(f'Línea {i}: {detalle}\n  Candidatos:\n{opciones}')
    r = gemini.json_estructurado(ELEGIR, [gemini.parte_texto('\n\n'.join(bloques))], ESQUEMA_ELEGIR)
    for e in r.datos.get('elecciones') or []:
        if not isinstance(e, dict) or not isinstance(e.get('linea'), int) or not 0 <= e['linea'] < len(lineas):
            continue
        x = lineas[e['linea']]
        elegido = next((p for p in x.candidatos if p.codigo == str(e.get('codigo') or '').strip()), None)
        if elegido and not x.producto:                   # código fuera de los candidatos → se ignora
            x.producto = elegido
            x.confianza = e.get('confianza') if e.get('confianza') in ('alta', 'media', 'baja') else 'baja'
    return r


# ── Todo junto ───────────────────────────────────────────────────────────────────────────────────────────────

def procesar(texto, archivos, perfil):
    texto = (texto or '').strip()[:MAX_TEXTO]
    if not texto and not archivos:
        raise ErrorPedido('Pega el mensaje o sube al menos una foto o PDF del pedido.')
    lineas, r1 = leer(texto, archivos)
    if not lineas:
        raise ErrorPedido('No se encontraron productos en el pedido. Revisa que la foto se vea bien o que el '
                          'mensaje traiga los productos.')
    cat = catalogo(perfil)
    for x in lineas:
        primera = x.texto.split()[0] if x.texto.split() else ''
        exacto = cat.exacto(x.codigo) or (cat.exacto(primera) if len(primera) >= 3 else None)
        if exacto:
            x.producto, x.confianza, x.candidatos = exacto, 'exacto', [exacto]
        else:
            x.candidatos = cat.candidatos(x)
    r2 = elegir(lineas)
    usados = [r for r in (r1, r2) if r]
    return Resultado(lineas, sum(r.tokens_entrada for r in usados), sum(r.tokens_salida for r in usados),
                     usados[0].modelo if usados else 'prueba')


def validar_archivos(archivos_subidos):
    """UploadedFile → [(bytes, tipo)] o ErrorPedido."""
    archivos = [a for a in archivos_subidos if a]
    if len(archivos) > MAX_ARCHIVOS:
        raise ErrorPedido(f'Máximo {MAX_ARCHIVOS} archivos por pedido.')
    salida, total = [], 0
    for a in archivos:
        tipo = (a.content_type or '').lower()
        if tipo == 'image/jpg':
            tipo = 'image/jpeg'
        if tipo not in TIPOS:
            raise ErrorPedido(f'«{a.name}»: solo se aceptan fotos (JPG, PNG, WEBP, HEIC) o PDF.')
        if a.size > MAX_BYTES_ARCHIVO:
            raise ErrorPedido(f'«{a.name}» pesa más de {MAX_BYTES_ARCHIVO // 1024 // 1024} MB.')
        total += a.size
        if total > MAX_BYTES_TOTAL:
            raise ErrorPedido(f'Los archivos juntos pasan de {MAX_BYTES_TOTAL // 1024 // 1024} MB.')
        salida.append((a.read(), tipo))
    return salida
