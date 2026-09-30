"""Utilidades comunes de formularios."""
from django import forms

from .tenancy import EmpresaModel, empresa_actual


class FormBootstrap:
    """
    Mixin para todos los formularios de Ordo:
      1. Recalcula los querysets de campos FK hacia modelos de empresa.
         Django arma esos querysets al importar el módulo, cuando todavía no hay
         empresa activa, y quedarían vacíos. Aquí se rehacen en cada request.
      2. Aplica las clases de Bootstrap a todos los widgets.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
