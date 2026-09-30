from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    """Login por correo con estilos de Bootstrap."""

    username = forms.EmailField(
        label='Correo',
        widget=forms.EmailInput(attrs={
            'class': 'form-control form-control-lg',
            'autocomplete': 'email',
            'autofocus': True,
            'placeholder': 'tucorreo@empresa.com',
        }),
    )
    password = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'autocomplete': 'current-password',
            'placeholder': '••••••••',
        }),
    )

    def clean_username(self):
        return self.cleaned_data['username'].lower()


from django.contrib.auth.forms import PasswordChangeForm  # noqa: E402

from apps.core.forms import FormBootstrap  # noqa: E402

from .models import Usuario  # noqa: E402


class PerfilForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ['first_name', 'last_name', 'telefono']
        labels = {'first_name': 'Nombre', 'last_name': 'Apellido'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True


class CambioClaveForm(FormBootstrap, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = 'Contraseña actual'
        self.fields['new_password2'].help_text = ''
