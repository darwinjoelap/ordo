from django import forms

from .models import PerfilEmpresa
from .servicios import validar_imagen

GRUPOS = {
    'identidad': ('Identidad', ['nombre_comercial', 'razon_social', 'rif', 'logo', 'color_principal']),
    'contacto': ('Contacto', ['direccion_fiscal', 'telefono', 'telefono_2', 'email', 'sitio_web',
                              'instagram', 'whatsapp']),
    'documentos': ('Documentos', ['prefijo_numeracion', 'condiciones_presupuesto', 'pie_documentos',
                                  'datos_bancarios', 'firma']),
    'comercial': ('Comercial', ['iva_porcentaje', 'dias_validez_presupuesto', 'dias_apartado', 'modo_precio',
                                'margen_minimo_pct', 'margen_maximo_pct', 'requiere_validacion',
                                'comision_requiere_pago']),
}


class PerfilEmpresaForm(forms.ModelForm):
    quitar_logo = forms.BooleanField(label='Quitar logo actual', required=False)
    quitar_firma = forms.BooleanField(label='Quitar firma actual', required=False)

    class Meta:
        model = PerfilEmpresa
        fields = [campo for _, campos in GRUPOS.values() for campo in campos]
        widgets = {
            'direccion_fiscal': forms.Textarea(attrs={'rows': 2}),
            'condiciones_presupuesto': forms.Textarea(attrs={'rows': 3}),
            'datos_bancarios': forms.Textarea(attrs={'rows': 3,
                                                     'placeholder': 'Banco, cuenta, titular, RIF, pago móvil…'}),
            'color_principal': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'logo': forms.FileInput(attrs={'accept': 'image/png,image/jpeg'}),
            'firma': forms.FileInput(attrs={'accept': 'image/png,image/jpeg'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre in ('quitar_logo', 'quitar_firma'):
            self.fields[nombre].widget.attrs['class'] = 'form-check-input'
        for nombre, campo in self.fields.items():
            w = campo.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault('class', 'form-check-input')
            elif isinstance(w, forms.Select):
                w.attrs.setdefault('class', 'form-select')
            elif nombre != 'color_principal':
                w.attrs.setdefault('class', 'form-control')

    def grupos(self):
        """[(clave, titulo, [bound fields])] para pintar las pestañas."""
        return [(clave, titulo, [self[c] for c in campos]) for clave, (titulo, campos) in GRUPOS.items()]

    def _validar_archivo(self, campo, etiqueta):
        archivo = self.cleaned_data.get(campo)
        if archivo and hasattr(archivo, 'content_type'):   # solo archivos recién subidos
            validar_imagen(archivo, etiqueta)
        return archivo

    def clean_logo(self):
        return self._validar_archivo('logo', 'El logo')

    def clean_firma(self):
        return self._validar_archivo('firma', 'La firma')

    def save(self, commit=True):
        perfil = super().save(commit=False)
        for campo in ('logo', 'firma'):
            if self.cleaned_data.get(f'quitar_{campo}') and not self.files.get(campo):
                archivo = getattr(perfil, campo)
                if archivo:
                    archivo.delete(save=False)
        if commit:
            perfil.save()
        return perfil

    def clean(self):
        datos = super().clean()
        minimo, maximo = datos.get('margen_minimo_pct'), datos.get('margen_maximo_pct')
        if minimo is not None and maximo is not None and maximo < minimo:
            self.add_error('margen_maximo_pct', 'El margen máximo no puede ser menor que el mínimo.')
        return datos
