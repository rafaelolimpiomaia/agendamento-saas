from django.db import models

class TenantManager(models.Manager):
    """
    Manager padrão que filtra automaticamente pelo tenant da requisição.
    Uso: Model.tenant_objects.all()  → já filtrado
    """

    def __init__(self, tenant_field='tenant'):
        super().__init__()
        self._tenant_field = tenant_field
        self._tenant = None

    def for_tenant(self, tenant):
        """Retorna queryset filtrado pelo tenant informado."""
        return self.filter(**{self._tenant_field: tenant})
