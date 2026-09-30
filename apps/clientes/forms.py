from django import forms

from apps.core.forms import FormBootstrap

from .models import Cliente


class ClienteForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['nombre', 'rif', 'contacto', 'telefono', 'email', 'direccion', 'notas', 'vendedor', 'activo']
        widgets = {'direccion': forms.Textarea(attrs={'rows': 2}), 'notas': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, puede_asignar=False, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if puede_asignar and empresa:
            from django.contrib.auth import get_user_model
            self.fields['vendedor'].queryset = get_user_model().objects.filter(
                membresias__empresa=empresa, membresias__activa=True).distinct()
        else:
            del self.fields['vendedor']

    def clean_rif(self):
        rif = self.cleaned_data['rif'].strip().upper()
        if rif:
            qs = Cliente.objects.filter(rif__iexact=rif).exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(f'Ya existe un cliente con ese RIF: {qs.first()}.')
        return rif
