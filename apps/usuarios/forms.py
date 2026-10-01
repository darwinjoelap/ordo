from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    """Login por nombre de usuario con estilos de Bootstrap."""

    username = forms.CharField(
        label='Usuario',
        max_length=60,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'autocomplete': 'username',
            'autocapitalize': 'none',
            'autofocus': True,
            'placeholder': 'tu usuario',
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
        return self.cleaned_data['username'].strip().lower()


from django.contrib.auth.forms import PasswordChangeForm  # noqa: E402

from apps.core.forms import FormBootstrap  # noqa: E402

from .models import Usuario  # noqa: E402


class PerfilForm(FormBootstrap, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ['first_name', 'last_name', 'email', 'telefono']
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
