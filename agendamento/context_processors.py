def tenant_context(request):
    """Disponibiliza tenant, tenant_slug e config em todos os templates."""
    tenant = getattr(request, 'tenant', None)

    config = None
    if tenant:
        try:
            config = tenant.configuracao
        except Exception:
            pass

    return {
        'tenant':      tenant,
        'tenant_slug': tenant.slug if tenant else '',
        'config':      config,
    }
