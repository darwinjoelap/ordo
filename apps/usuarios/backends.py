"""
Login por usuario dentro de una empresa.

- En el enlace de una empresa (/<slug>/) la vista deja `request.empresa_login`: se busca el usuario de ESA empresa.
- En la dirección principal y en /admin/ no hay empresa: solo entran cuentas de plataforma (sin empresa).
- En el login de una empresa, si no existe ese usuario en la empresa, puede entrar una cuenta de plataforma
  de soporte (es_soporte o superusuario): queda en «Modo soporte», sin ser miembro.
"""
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from .models import Usuario, normalizar_usuario


class UsuarioPorEmpresaBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        empresa = getattr(request, 'empresa_login', None) if request is not None else None
        filtro = {'empresa_cuenta': empresa} if empresa is not None else {'empresa_cuenta__isnull': True}
        username = normalizar_usuario(username)
        usuario = Usuario.objects.filter(username=username, **filtro).first()
        if usuario is None and empresa is not None:      # soporte Ordo: el usuario de la empresa tiene prioridad
            usuario = (Usuario.objects.filter(username=username, empresa_cuenta__isnull=True)
                       .filter(Q(es_soporte=True) | Q(is_superuser=True)).first())
        if usuario is None:
            Usuario().set_password(password)      # mismo tiempo de respuesta exista o no
            return None
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None
