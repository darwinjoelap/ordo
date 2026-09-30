from django import forms

from apps.core.forms import FormBootstrap
from apps.inventario.models import Producto
from apps.proveedores.models import Proveedor

from .models import OrdenCompra


class OrdenForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = OrdenCompra
        fields = ['proveedor', 'notas']
        widgets = {'notas': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['proveedor'].queryset = Proveedor.objects.filter(activo=True)


class ItemForm(FormBootstrap, forms.Form):
    producto = forms.ModelChoiceField(queryset=Producto.objects.none(), widget=forms.HiddenInput)
    cantidad = forms.IntegerField(min_value=1)
    costo = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['producto'].queryset = Producto.objects.filter(activo=True)
