from django import forms

from apps.core.forms import FormBootstrap, validar_unico_en_empresa

from .models import Proveedor


class ProveedorForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = ['nombre', 'rif', 'contacto', 'telefono', 'email', 'direccion', 'notas', 'activo']
        widgets = {
            'direccion': forms.Textarea(attrs={'rows': 2}),
            'notas': forms.Textarea(attrs={'rows': 2}),
        }

    def clean_nombre(self):
        return validar_unico_en_empresa(self, 'nombre', 'Ya existe un proveedor con ese nombre.')
