from django import forms

from django.contrib.auth.validators import UnicodeUsernameValidator

from apps.core.forms import FormBootstrap

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
                                'vendedores_ven_todos_los_clientes', 'comision_requiere_pago']),
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
        for nombre in ('razon_social', 'rif'):          # los administra la plataforma (panel de empresas)
            self.fields[nombre].disabled = True
            self.fields[nombre].help_text = 'Lo actualiza el equipo de Ordo. Escríbenos si hay que corregirlo.'
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


class InvitarForm(FormBootstrap, forms.Form):
    username = forms.CharField(label='Usuario', max_length=60, help_text='Para entrar. Ej.: maria, jperez.',
                               validators=[UnicodeUsernameValidator()])
    nombre = forms.CharField(label='Nombre', max_length=150)
    apellido = forms.CharField(label='Apellido', max_length=150)
    email = forms.EmailField(label='Correo (opcional)', required=False)
    rol = forms.ChoiceField(label='Rol')

    def __init__(self, *args, roles=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rol'].choices = roles


# ── Panel de plataforma ───────────────────────────────────────────────────────

from .models import Empresa  # noqa: E402


class _EmpresaPlataformaBase(FormBootstrap, forms.Form):
    nombre_comercial = forms.CharField(label='Nombre comercial', max_length=150)
    razon_social = forms.CharField(label='Razón social', max_length=200, required=False)
    rif = forms.CharField(label='RIF', max_length=20, required=False)
    slug = forms.CharField(label='Enlace', max_length=40,
                           help_text='Queda como https://<dominio>/<enlace>/ — minúsculas, números y guiones.')
    plan = forms.ChoiceField(label='Plan', choices=Empresa.Plan.choices)
    activa_hasta = forms.DateField(label='Pagado / activa hasta', required=False,
                                   widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                                   help_text='Vacío = sin vencimiento.')
    limite_usuarios = forms.IntegerField(label='Límite de usuarios activos', required=False, min_value=1,
                                         help_text='Vacío = sin límite.')
    notas = forms.CharField(label='Notas internas', required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, empresa=None, **kwargs):
        self.empresa = empresa
        super().__init__(*args, **kwargs)

    def clean_slug(self):
        from .plataforma import validar_enlace
        return validar_enlace(self.cleaned_data['slug'], excluir_pk=self.empresa.pk if self.empresa else None)

    def clean_rif(self):
        return self.cleaned_data['rif'].strip().upper()


class NuevaEmpresaForm(_EmpresaPlataformaBase):
    usuario_dueno = forms.CharField(label='Usuario del Dueño', max_length=60, validators=[UnicodeUsernameValidator()])
    email_dueno = forms.EmailField(label='Correo del Dueño (opcional)', required=False)
    nombre_dueno = forms.CharField(label='Nombre del Dueño', max_length=150, required=False)
    apellido_dueno = forms.CharField(label='Apellido del Dueño', max_length=150, required=False)


class EditarEmpresaForm(_EmpresaPlataformaBase):
    estado = forms.ChoiceField(label='Estado', choices=Empresa.Estado.choices)
