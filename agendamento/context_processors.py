def tenant_context(request):
    """Disponibiliza request.tenant e tenant_slug em todos os templates."""
    tenant = getattr(request, 'tenant', None)
    return {
        'tenant': tenant,
        'tenant_slug': tenant.slug if tenant else '',
    }
