from django.http import Http404
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator


class TenantMixin:
    """
    Mixin para views baseadas em classe.
    Garante que request.tenant está presente e disponibiliza self.tenant.
    """
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request, 'tenant') or request.tenant is None:
            raise Http404('Salão não encontrado.')
        self.tenant = request.tenant
        return super().dispatch(request, *args, **kwargs)


# ── Para views baseadas em função (decorator) ──────────────────────
def require_tenant(view_func):
    """
    Decorator para views baseadas em função.
    Garante que request.tenant existe antes de entrar na view.
    """
    def wrapper(request, *args, **kwargs):
        if not hasattr(request, 'tenant') or request.tenant is None:
            raise Http404('Salão não encontrado.')
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper
