from django.http import Http404
from django.core.cache import cache
from .models import Tenant
import logging

logger = logging.getLogger('seguranca')


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        if request.is_secure():
            response['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains; preload'
            )
        return response


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        slug = self._extrair_slug(request.path)

        if slug:
            tenant = self._carregar_tenant(slug)
            if tenant is None:
                raise Http404('Salão não encontrado.')

            request.tenant = tenant

            from master.models import StatusSalao
            status_admin = StatusSalao.objects.filter(tenant=tenant).first()

            if status_admin:
                if status_admin.esta_suspenso:
                    raise Http404('Salão indisponível.')
                request.tenant_congelado = status_admin.esta_congelado
            else:
                request.tenant_congelado = False
        else:
            request.tenant = None
            request.tenant_congelado = False

        return self.get_response(request)

    def _extrair_slug(self, path):
        partes = path.strip('/').split('/')
        if partes and partes[0]:
            ignorar = {
                'admin', 'static', 'media', 'cadastro', 'entrar',
                'termos', 'privacidade', 'master', 'favicon.ico', 'webhook',
            }
            if partes[0] not in ignorar:
                return partes[0]
        return None

    def _carregar_tenant(self, slug):
        cache_key = f'tenant:{slug}'
        tenant = cache.get(cache_key)
        if tenant is None:
            tenant = Tenant.objects.filter(slug=slug, ativo=True).first()
            if tenant:
                cache.set(cache_key, tenant, 300)
        return tenant