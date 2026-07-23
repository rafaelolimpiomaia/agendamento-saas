from django.http import Http404
from django.core.cache import cache
from .models import Tenant


class TenantMiddleware:
    """
    Extrai o slug do tenant da URL no formato:
        /<slug>/...
    e disponibiliza request.tenant para toda a aplicação.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        slug = self._extrair_slug(request.path)

        if slug:
            tenant = self._carregar_tenant(slug)
            if tenant is None:
                raise Http404('Salão não encontrado.')
            request.tenant = tenant
        else:
            request.tenant = None  # URL pública (cadastro, landing)

        return self.get_response(request)

    def _extrair_slug(self, path):
        """Extrai o primeiro segmento da URL como slug do tenant."""
        partes = path.strip('/').split('/')
        if partes and partes[0]:
            # Ignora URLs de admin Django, static e media
            ignorar = {'admin', 'static', 'media', 'cadastro','entrar', 'termos', 'privacidade', 'favicon.ico'}
            if partes[0] not in ignorar:
                return partes[0]
        return None

    def _carregar_tenant(self, slug):
        """Carrega tenant do cache ou banco. Cache de 5 min por slug."""
        cache_key = f'tenant:{slug}'
        tenant = cache.get(cache_key)
        if tenant is None:
            tenant = Tenant.objects.filter(slug=slug, ativo=True).first()
            if tenant:
                cache.set(cache_key, tenant, 300)  # 5 minutos
        return tenant
