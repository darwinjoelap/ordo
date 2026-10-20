"""Utilidades comunes de formularios."""
from django import forms

from .numeros import numero
from .tenancy import EmpresaModel, empresa_actual


class DecimalTolerante(forms.DecimalField):
    """Acepta 12,50 · 12.50 · 1.234,50 (lo que escribe la gente en Venezuela). Se usa en todo formulario de Ordo."""

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, str):
            leido = numero(value)
            if leido is None:
                raise forms.ValidationError(self.error_messages['invalid'], code='invalid')
            value = str(leido)
        return super().to_python(value)


def decimales_tolerantes(form):
    """Cambia cada DecimalField del formulario por uno tolerante con caja de texto (el navegador no borra la coma)."""
    for campo in form.fields.values():
        if isinstance(campo, forms.DecimalField) and not isinstance(campo, DecimalTolerante):
            campo.__class__ = DecimalTolerante
            attrs = {k: v for k, v in campo.widget.attrs.items() if k not in ('step', 'min', 'max', 'type')}
            attrs.update({'inputmode': 'decimal', 'autocomplete': 'off'})
            campo.widget = forms.TextInput(attrs=attrs)
            campo.widget.is_localized = False


class FormBootstrap:
    """
    Mixin para todos los formularios de Ordo:
      1. Recalcula los querysets de campos FK hacia modelos de empresa.
         Django arma esos querysets al importar el módulo, cuando todavía no hay
         empresa activa, y quedarían vacíos. Aquí se rehacen en cada request.
      2. Aplica las clases de Bootstrap a todos los widgets.
      3. Los decimales aceptan coma o punto (DecimalTolerante).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        decimales_tolerantes(self)
        for campo in self.fields.values():
            if isinstance(campo, forms.ModelChoiceField) and issubclass(campo.queryset.model, EmpresaModel):
                campo.queryset = campo.queryset.model.objects.all()
        for campo in self.fields.values():
            w = campo.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault('class', 'form-check-input')
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault('class', 'form-select')
            else:
                w.attrs.setdefault('class', 'form-control')


def validar_unico_en_empresa(form, campo, mensaje):
    """
    La unicidad es por empresa (UniqueConstraint con `empresa`), pero `empresa` no está
    en el formulario, así que Django no la valida: se valida aquí para mostrar un error
    amable en vez de un IntegrityError.
    """
    valor = form.cleaned_data.get(campo)
    if valor in (None, ''):
        return valor
    modelo = form._meta.model
    qs = modelo.objects.filter(**{f'{campo}__iexact' if isinstance(valor, str) else campo: valor})
    if form.instance.pk:
        qs = qs.exclude(pk=form.instance.pk)
    if empresa_actual() is not None and qs.exists():
        raise forms.ValidationError(mensaje)
    return valor
