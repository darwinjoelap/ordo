"""
Cargar un presupuesto desde un pedido con IA (texto pegado, fotos o PDF). Método en dos pasos para gastar poco:

1. LEER: la IA solo transcribe el pedido a líneas {texto, código, cantidad, unidad}. No ve el inventario.
2. BUSCAR: Ordo busca candidatos en el inventario de la empresa (código exacto, o palabras del nombre/marca/código).
3. ELEGIR: solo para las líneas sin código exacto, la IA elige entre ESOS candidatos (no puede inventar productos).

El resultado se revisa en pantalla antes de agregar nada; se agrega con `servicios.agregar_item` (precios, rangos,
IVA y stock como siempre). El pedido no se guarda: pasa por memoria y se descarta.
"""
import difflib
import math
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
    grupo: str = ''                                        # título del pedido que agrupa la línea («Bacteriología»)
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

# Unidades escritas de varias formas → una sola («20LT» = «x 20 L», «30GRS» = «x 30 G»)
UNIDADES = {'lt': 'l', 'lts': 'l', 'litro': 'l', 'litros': 'l', 'gr': 'g', 'grs': 'g', 'gramos': 'g', 'gramo': 'g',
            'kgs': 'kg', 'kilo': 'kg', 'kilos': 'kg', 'gal': 'gl', 'galon': 'gl', 'galones': 'gl', 'ml': 'ml',
            'cc': 'ml', 'und': 'un', 'unid': 'un', 'unidad': 'un', 'unidades': 'un'}


def normalizar(texto):
    """Minúsculas, sin acentos ni signos; separa números de letras («30mcg» → «30 mcg», «x50» → «x 50»)
    y unifica unidades («lt» → «l», «grs» → «g», «galon» → «gl»)."""
    texto = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode().lower()
    texto = re.sub(r'(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)', ' ', texto)
    return ' '.join(UNIDADES.get(w, w) for w in re.sub(r'[^a-z0-9%]+', ' ', texto).split())


def _palabras(texto):
    vistas, salida = set(), []
    for p in normalizar(texto).split():
        if (len(p) >= 2 or p.isdigit()) and p not in vistas:
            vistas.add(p)
            salida.append(p)
    return salida


class Catalogo:
    """
    El inventario activo de la empresa, normalizado una vez por pedido.

    Puntaje de un producto para una línea del pedido = suma, por cada palabra del pedido, de
    (parecido con la mejor palabra del producto) × (peso de esa palabra). El peso es mayor cuanto MENOS productos la
    tienen: «discos», «mcg», «x50» casi no cuentan; «aztreonam» decide. El parecido tolera errores de escritura
    («imipenen» → imipenem, «trimetropin» → sulfatrimetropim, «cefuroxime» → cefuroxima).
    """

    def __init__(self, productos):
        self.productos = list(productos)
        self.por_codigo = {normalizar(p.codigo).replace(' ', ''): p for p in self.productos if p.codigo}
        self.indice = {}                                    # palabra → [posición del producto]
        for i, p in enumerate(self.productos):
            texto = f'{p.codigo} {p.nombre} {p.marca.nombre if p.marca_id else ""}'
            for w in set(normalizar(texto).split()):
                self.indice.setdefault(w, []).append(i)
        total = max(len(self.productos), 1)
        self.peso = {w: math.log(1 + total / len(ps)) for w, ps in self.indice.items()}
        self._parecidos = {}

    def exacto(self, *codigos):
        for codigo in codigos:
            clave = normalizar(codigo).replace(' ', '')
            if clave and clave in self.por_codigo:
                return self.por_codigo[clave]
        return None

    def parecidos(self, palabra):
        """({palabra del inventario: parecido 0..1}, peso) para una palabra del pedido (con caché por pedido)."""
        if palabra in self._parecidos:
            return self._parecidos[palabra]
        salida = {}
        if palabra in self.peso:
            salida[palabra] = 1.0
        if len(palabra) >= 4 and not palabra.isdigit():
            for w in self.peso:
                if w == palabra or len(w) < 4 or w.isdigit():
                    continue
                contenida = palabra in w or w in palabra
                if not contenida and (abs(len(w) - len(palabra)) > 4 or not set(palabra[:3]) & set(w)):
                    continue                                # muy distinta: no vale la pena compararla
                m = difflib.SequenceMatcher(None, palabra, w)
                if contenida:                               # «sulfa» ⊂ «sulfatrimetropim», «ampicilin» ⊂ «ampicilina»
                    # contenida: al menos 0,7, pero gana la más parecida («ofloxacina» → ofloxacino, no levofloxacina)
                    salida[w] = max(salida.get(w, 0), m.ratio(), 0.7)
                elif m.real_quick_ratio() >= 0.75 and m.quick_ratio() >= 0.75:
                    r = m.ratio()                           # errores de escritura: «imipenen» → imipenem
                    if r >= 0.75:
                        salida[w] = max(salida.get(w, 0), r)
        for w, r in salida.items():                         # mismo comienzo desempata: «ofloxacina» → ofloxacino
            if w != palabra and w[:3] == palabra[:3]:
                salida[w] = min(1.0, r + 0.05)
        # El peso de la palabra del pedido es el de su mejor equivalente en el inventario (igual para todos los
        # productos): así «ampicilina» pesa como «ampicilin» y no gana «amoxicilina» por ser más rara.
        peso = self.peso[max(salida, key=salida.get)] if salida else 0
        if palabra in UNIDADES.values() or palabra in ('x', 'un', 'caja', 'bidon', 'saco', 'pipa'):
            peso *= 0.25                                    # presentación: ayuda a desempatar, no a decidir
        elif palabra.isdigit():
            peso *= 0.5                                     # concentraciones y tamaños: igual
        self._parecidos[palabra] = (salida, peso)
        return self._parecidos[palabra]

    def candidatos(self, linea):
        palabras = _palabras(f'{linea.texto} {linea.codigo}')
        if not palabras:
            return []
        total = {}
        for palabra in palabras:
            mapa, peso = self.parecidos(palabra)
            mejor = {}                                      # producto → mejor parecido para esta palabra
            for w, parecido in mapa.items():
                for i in self.indice[w]:
                    if parecido > mejor.get(i, 0):
                        mejor[i] = parecido
            for i, parecido in mejor.items():
                total[i] = total.get(i, 0) + peso * parecido
        puntajes = [(puntos, self.productos[i].nombre, self.productos[i]) for i, puntos in total.items() if puntos > 0]
        sin_precio = lambda p: not getattr(p, 'precio_venta_usd', 1)          # noqa: E731  (duplicados en $0 al final)
        if not puntajes:
            return []
        puntajes.sort(key=lambda x: (-round(x[0], 3), sin_precio(x[2]), x[1]))
        tope = puntajes[0][0]
        # Solo los que se acercan al mejor: si nada más que «discos» coincide, no se llena la lista de ruido
        return [p for puntos, _, p in puntajes[:MAX_CANDIDATOS] if puntos >= tope * 0.35]


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
- texto: el producto tal como aparece (siglas, marca, presentación, concentración), SIN la cantidad. Corrige solo la
  ortografía evidente si se lee claro; no cambies el producto.
- codigo: si la línea trae un código o referencia de producto (columna Código, Ref., Cód.), cópialo exacto; si no, "".
- cantidad: unidades pedidas, solo la cifra. Si la línea NO indica cantidad, 0 (no supongas 1).
- unidad: la presentación o unidad si aparece (saco, galón, litro, caja, kg, frasco, discos…), si no "".
- grupo: si el pedido tiene títulos que agrupan productos (p. ej. «Bacteriología», «Química», «Herbicidas»),
  el título bajo el que está la línea; si no, "". Los títulos NO son líneas.

Listas escritas a mano: las comillas o marcas de repetición (", ″, 〃, «id.», «ídem») repiten la palabra de la línea
de arriba; escribe la línea completa (debajo de «Agar base sangre», 〃 CLED = «Agar CLED»).

Documentos impresos (órdenes de compra, notas de entrega, facturas): toma solo la tabla de productos. Las cantidades
pueden venir con decimales y coma («11,00» = 11). Ignora marcas como «(E)» de exento. Si llegan VARIAS fotos o
páginas del MISMO documento (mismo número o mismas líneas), cuenta cada línea UNA sola vez.

No incluyas precios, totales, datos del cliente, direcciones, firmas ni saludos. No inventes productos. Si una parte
no se lee bien, escribe lo que se lea y agrega "(?)" al final del texto."""

ESQUEMA_LEER = {'type': 'object', 'required': ['lineas'], 'properties': {
    'lineas': {'type': 'array', 'items': {'type': 'object', 'required': ['texto', 'cantidad'], 'properties': {
        'texto': {'type': 'string'}, 'codigo': {'type': 'string'}, 'cantidad': {'type': 'number'},
        'unidad': {'type': 'string'}, 'grupo': {'type': 'string'}}}}}}


def _cantidad(valor):
    """(cantidad entera ≥ 1, nota si se ajustó)."""
    try:
        numero = float(str(valor).replace(',', '.'))
    except (TypeError, ValueError):
        return 1, 'El pedido no dice la cantidad: se puso 1.'
    if numero <= 0:
        return 1, 'El pedido no dice la cantidad: se puso 1.'
    entero = max(1, round(numero))
    return entero, ('' if entero == numero else f'El pedido dice {valor}: se redondeó a {entero}.')


def _lineas_de(datos):
    lineas = []
    for d in (datos.get('lineas') or [])[:MAX_LINEAS]:
        if not isinstance(d, dict) or not str(d.get('texto') or '').strip():
            continue
        cantidad, nota = _cantidad(d.get('cantidad'))
        texto, unidad = str(d['texto']).strip()[:200], str(d.get('unidad') or '').strip()[:40]
        cantidad, nota = _por_caja(texto, unidad, cantidad, nota)
        lineas.append(Linea(texto=texto, codigo=str(d.get('codigo') or '').strip()[:50], cantidad=cantidad,
                            unidad=unidad, grupo=str(d.get('grupo') or '').strip()[:60], nota=nota))
    return lineas


RE_CAJA = re.compile(r'\b1\s*x\s*(\d{1,3})\b', re.I)
CAJAS = {'caj', 'caja', 'cajas', 'cj', 'bulto', 'bultos', 'paq', 'paquete', 'pqt'}


def _por_caja(texto, unidad, cantidad, nota):
    """«PH AN30 1X6 LT» · 1 Caj → 6 unidades (con aviso). Solo si la línea dice caja y trae «1xN»."""
    m = RE_CAJA.search(texto)
    primera = (normalizar(unidad).split() or [''])[0]
    if not m or primera not in CAJAS:
        return cantidad, nota
    por_caja = int(m.group(1))
    if por_caja < 2:
        return cantidad, nota
    aviso = (f'{cantidad} caja{"s" if cantidad > 1 else ""} de {por_caja}: se cuentan {cantidad * por_caja} unidades. '
             'Si vendes la caja como un producto, cámbialo a ' + str(cantidad) + '.')
    return cantidad * por_caja, f'{nota} {aviso}'.strip()


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
de esa línea (por su código). Usa siglas, abreviaturas, nombres en otro idioma o mal escritos (cefuroxime =
cefuroxima, trimetropin sulfa = sulfatrimetoprim), marca, presentación, concentración, unidad y el grupo del pedido.
- Si es el mismo producto pero la concentración o presentación del pedido no coincide (pide 10 mcg y hay 300 mcg),
  elígelo con confianza "media": el vendedor lo verifica.
- Si hay dos productos iguales en el inventario, prefiere el que tiene precio (no el marcado SIN PRECIO).
- Elige la presentación que corresponda (galón, litro, bidón de 20 L, saco) si el inventario las separa.
- Si el producto pedido NO está entre los candidatos (otro principio activo, otro medio de cultivo, otro artículo),
  devuelve codigo "". No elijas algo solo porque comparte palabras genéricas (agar, discos, saco, galón).
confianza: "alta" si es claramente ese producto; "media" si es probable o difiere en concentración; "baja" si dudas."""

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
    if not getattr(p, 'precio_venta_usd', 1):
        partes.append('SIN PRECIO')
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
                  (f' (unidad: {x.unidad})' if x.unidad else '') + (f' (grupo: {x.grupo})' if x.grupo else '')
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
