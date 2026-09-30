from django import forms
from django.urls import reverse

from apps.core.forms import FormBootstrap, validar_unico_en_empresa
from apps.proveedores.models import Proveedor

from .models import Categoria, Lote, Marca, MovimientoInventario, Producto, Subcategoria, Unidad


class ProductoForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = Producto
        fields = ['codigo', 'nombre', 'descripcion', 'categoria', 'subcategoria', 'marca', 'unidad',
                  'proveedor_habitual', 'maneja_lotes', 'maneja_vencimiento', 'precio_costo_usd',
                  'precio_venta_usd', 'stock_minimo', 'factor_venta_dias', 'activo']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 2}),
            'precio_costo_usd': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'precio_venta_usd': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'factor_venta_dias': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['marca'].queryset = Marca.objects.filter(activa=True)
        self.fields['proveedor_habitual'].queryset = Proveedor.objects.filter(activo=True)
        # Subcategorías de la categoría elegida (POST) o de la del producto
        categoria_id = self.data.get(self.add_prefix('categoria')) or self.instance.categoria_id
        self.fields['subcategoria'].queryset = (
            Subcategoria.objects.filter(categoria_id=categoria_id) if categoria_id else Subcategoria.objects.none())
        self.fields['categoria'].widget.attrs.update({
            'hx-get': reverse('inventario:subcategorias_opciones'), 'hx-target': '#id_subcategoria',
            'hx-trigger': 'change'})

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo'].strip().upper()
        self.cleaned_data['codigo'] = codigo
        return validar_unico_en_empresa(self, 'codigo', 'Ya existe un producto con ese código.')

    def clean(self):
        datos = super().clean()
        sub, cat = datos.get('subcategoria'), datos.get('categoria')
        if sub and cat and sub.categoria_id != cat.pk:
            self.add_error('subcategoria', 'La subcategoría no pertenece a la categoría elegida.')
        return datos


class IngresoForm(FormBootstrap, forms.Form):
    producto = forms.ModelChoiceField(queryset=Producto.objects.none(), widget=forms.HiddenInput)
    proveedor = forms.ModelChoiceField(queryset=Proveedor.objects.none(), required=False, label='Proveedor')
    numero_lote = forms.CharField(max_length=50, required=False, label='Número de lote')
    fecha_vencimiento = forms.DateField(required=False, label='Vencimiento',
                                        widget=forms.DateInput(attrs={'type': 'date'}))
    cantidad = forms.IntegerField(min_value=1, label='Cantidad')
    costo_unitario = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, label='Costo unitario (USD)',
                                        widget=forms.NumberInput(attrs={'step': '0.01'}))
    notas = forms.CharField(required=False, label='Notas', widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['producto'].queryset = Producto.objects.filter(activo=True)
        self.fields['proveedor'].queryset = Proveedor.objects.filter(activo=True)

    def clean(self):
        datos = super().clean()
        p = datos.get('producto')
        if p:
            if p.maneja_lotes and not datos.get('numero_lote'):
                self.add_error('numero_lote', 'Este producto requiere número de lote.')
            if p.maneja_vencimiento and not datos.get('fecha_vencimiento'):
                self.add_error('fecha_vencimiento', 'Este producto requiere fecha de vencimiento.')
        return datos


class AjusteForm(FormBootstrap, forms.Form):
    TIPOS = [
        (MovimientoInventario.Tipo.AJUSTE_POS, 'Ajuste positivo (agregar)'),
        (MovimientoInventario.Tipo.AJUSTE_NEG, 'Ajuste negativo (retirar)'),
        (MovimientoInventario.Tipo.BAJA_VENC, 'Baja por vencimiento'),
    ]
    producto = forms.ModelChoiceField(queryset=Producto.objects.none(), widget=forms.HiddenInput)
    lote = forms.ModelChoiceField(queryset=Lote.objects.none(), label='Lote')
    tipo = forms.ChoiceField(choices=TIPOS, label='Tipo de ajuste')
    cantidad = forms.IntegerField(min_value=1, label='Cantidad')
    motivo = forms.CharField(max_length=250, label='Motivo', widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['producto'].queryset = Producto.objects.all()
        producto_id = self.data.get('producto') or self.initial.get('producto')
        self.fields['lote'].queryset = (
            Lote.objects.filter(producto_id=producto_id, cantidad_actual__gt=0) if producto_id else Lote.objects.none())


# ── Catálogo simple ───────────────────────────────────────────────────────────

class CategoriaForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre', 'descripcion']
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 2})}

    def clean_nombre(self):
        return validar_unico_en_empresa(self, 'nombre', 'Ya existe una categoría con ese nombre.')


class SubcategoriaForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = Subcategoria
        fields = ['categoria', 'nombre']

    def clean(self):
        datos = super().clean()
        cat, nombre = datos.get('categoria'), datos.get('nombre')
        if cat and nombre:
            qs = Subcategoria.objects.filter(categoria=cat, nombre__iexact=nombre).exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error('nombre', 'Esa subcategoría ya existe en la categoría.')
        return datos


class MarcaForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = Marca
        fields = ['nombre', 'activa']

    def clean_nombre(self):
        return validar_unico_en_empresa(self, 'nombre', 'Ya existe una marca con ese nombre.')


class UnidadForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = Unidad
        fields = ['nombre', 'abreviatura']

    def clean_abreviatura(self):
        self.cleaned_data['abreviatura'] = self.cleaned_data['abreviatura'].strip().upper()
        return validar_unico_en_empresa(self, 'abreviatura', 'Ya existe una unidad con esa abreviatura.')
