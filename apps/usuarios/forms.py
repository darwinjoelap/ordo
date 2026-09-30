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
