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
    costo = forms.CharField(max_length=20)

    def clean_costo(self):
        from decimal import Decimal

        from apps.core.numeros import numero
        valor = numero(self.cleaned_data['costo'])
        if valor is None or valor < 0:
            raise forms.ValidationError('Costo inválido (ej.: 12.50 o 12,50).')
        return valor.quantize(Decimal('0.01'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['producto'].queryset = Producto.objects.filter(activo=True).fisicos()
