from django.db.models import Count, Q
from functools import wraps
from django.shortcuts import redirect, get_object_or_404, render
from .models import SuperAdminUser, StatusSalao, LogAdministrativo
from agendamento.models import Tenant, Cliente, Agendamento, CodigoConvite
from django.utils import timezone
from django.contrib import messages

def super_admin_required(view_func):
    """
    Protege views do Painel Master.
    Verifica sessão própria (master_admin_id) — nunca request.user.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        admin_id = request.session.get('master_admin_id')

        if not admin_id:
            return redirect('master_login')

        try:
            admin = SuperAdminUser.objects.get(id=admin_id, ativo=True)
        except SuperAdminUser.DoesNotExist:
            request.session.pop('master_admin_id', None)
            return redirect('master_login')

        request.super_admin = admin  # disponibiliza no request
        return view_func(request, *args, **kwargs)

    return wrapper

@super_admin_required
def master_dashboard(request):
    total_saloes     = Tenant.objects.count()
    saloes_ativos    = StatusSalao.objects.filter(status='ativo').count()
    saloes_teste     = StatusSalao.objects.filter(status='teste').count()
    saloes_congelados = StatusSalao.objects.filter(status='congelado').count()
    saloes_suspensos = StatusSalao.objects.filter(status='suspenso').count()

    total_clientes      = Cliente.objects.count()
    total_agendamentos  = Agendamento.objects.count()

    ultimos_saloes = Tenant.objects.order_by('-criado_em')[:5]
    ultimas_acoes  = LogAdministrativo.objects.select_related('tenant', 'super_admin')[:8]

    codigos_disponiveis = CodigoConvite.objects.filter(usado=False).count()
    codigos_usados       = CodigoConvite.objects.filter(usado=True).count()

    return render(request, 'master/dashboard.html', {
        'total_saloes': total_saloes,
        'saloes_ativos': saloes_ativos,
        'saloes_teste': saloes_teste,
        'saloes_congelados': saloes_congelados,
        'saloes_suspensos': saloes_suspensos,
        'total_clientes': total_clientes,
        'total_agendamentos': total_agendamentos,
        'ultimos_saloes': ultimos_saloes,
        'ultimas_acoes': ultimas_acoes,
        'codigos_disponiveis': codigos_disponiveis,
        'codigos_usados': codigos_usados,
    })

@super_admin_required
def listar_saloes(request):
    q = request.GET.get('q', '').strip()
    status_filtro = request.GET.get('status', '')

    tenants = Tenant.objects.select_related('status_admin').all()

    if q:
        tenants = tenants.filter(
            Q(nome__icontains=q) | Q(slug__icontains=q) | Q(email__icontains=q)
        )

    if status_filtro:
        tenants = tenants.filter(status_admin__status=status_filtro)

    saloes_data = []
    for t in tenants:
        status_admin, _ = StatusSalao.objects.get_or_create(tenant=t)
        saloes_data.append({
            'tenant': t,
            'status_admin': status_admin,
            'total_clientes': Cliente.objects.filter(tenant=t).count(),
            'total_agendamentos': Agendamento.objects.filter(tenant=t).count(),
            'total_servicos': t.servicos.count(),
        })

    return render(request, 'master/listar_saloes.html', {
        'saloes_data': saloes_data,
        'q': q,
        'status_filtro': status_filtro,
        'status_choices': StatusSalao.STATUS_CHOICES,
    })


@super_admin_required
def detalhes_salao(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    status_admin, _ = StatusSalao.objects.get_or_create(tenant=tenant)

    if request.method == 'POST':
        status_admin.observacoes_internas = request.POST.get('observacoes', '')
        status_admin.pagamento_em_dia = request.POST.get('pagamento_em_dia') == 'on'

        vencimento = request.POST.get('vencimento')
        if vencimento:
            status_admin.vencimento = vencimento

        status_admin.save()

        LogAdministrativo.objects.create(
            super_admin=request.super_admin,
            tenant=tenant,
            acao='editar',
            detalhes='Informações administrativas atualizadas.',
        )
        messages.success(request, 'Informações atualizadas com sucesso.')
        return redirect('master_detalhes_salao', tenant_id=tenant.id)

    dados = {
        'tenant': tenant,
        'status_admin': status_admin,
        'total_clientes': Cliente.objects.filter(tenant=tenant).count(),
        'total_agendamentos': Agendamento.objects.filter(tenant=tenant).count(),
        'total_servicos': tenant.servicos.count(),
        'logs': LogAdministrativo.objects.filter(tenant=tenant)[:15],
    }
    return render(request, 'master/detalhes_salao.html', dados)

@super_admin_required
def congelar_salao(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    status_admin, _ = StatusSalao.objects.get_or_create(tenant=tenant)

    if request.method == 'POST':
        motivo = request.POST.get('motivo', '').strip()
        status_admin.status = 'congelado'
        status_admin.congelado_em = timezone.now()
        status_admin.congelado_motivo = motivo
        status_admin.save()

        LogAdministrativo.objects.create(
            super_admin=request.super_admin,
            tenant=tenant,
            acao='congelar',
            detalhes=motivo or 'Sem motivo informado.',
        )
        messages.success(request, f'Salão "{tenant.nome}" congelado com sucesso.')
        return redirect('master_detalhes_salao', tenant_id=tenant.id)

    return render(request, 'master/confirmar_acao.html', {
        'tenant': tenant,
        'acao': 'congelar',
        'titulo': 'Congelar salão?',
        'descricao': 'Clientes não conseguirão criar novos agendamentos. O admin do salão continuará com acesso ao painel.',
        'pedir_motivo': True,
    })


@super_admin_required
def reativar_salao(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    status_admin, _ = StatusSalao.objects.get_or_create(tenant=tenant)

    if request.method == 'POST':
        status_admin.status = 'ativo'
        status_admin.congelado_em = None
        status_admin.congelado_motivo = ''
        status_admin.save()

        LogAdministrativo.objects.create(
            super_admin=request.super_admin,
            tenant=tenant,
            acao='reativar',
        )
        messages.success(request, f'Salão "{tenant.nome}" reativado com sucesso.')
        return redirect('master_detalhes_salao', tenant_id=tenant.id)

    return render(request, 'master/confirmar_acao.html', {
        'tenant': tenant,
        'acao': 'reativar',
        'titulo': 'Reativar salão?',
        'descricao': 'O salão voltará a funcionar normalmente para clientes e administrador.',
    })


@super_admin_required
def suspender_salao(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    status_admin, _ = StatusSalao.objects.get_or_create(tenant=tenant)

    if request.method == 'POST':
        motivo = request.POST.get('motivo', '').strip()
        status_admin.status = 'suspenso'
        status_admin.save()
        tenant.ativo = False
        tenant.save()

        LogAdministrativo.objects.create(
            super_admin=request.super_admin,
            tenant=tenant,
            acao='suspender',
            detalhes=motivo or 'Sem motivo informado.',
        )
        messages.success(request, f'Salão "{tenant.nome}" suspenso.')
        return redirect('master_detalhes_salao', tenant_id=tenant.id)

    return render(request, 'master/confirmar_acao.html', {
        'tenant': tenant,
        'acao': 'suspender',
        'titulo': 'Suspender salão?',
        'descricao': 'Nem admin nem clientes conseguirão acessar o sistema. Diferente do congelamento, aqui o acesso é totalmente bloqueado.',
        'pedir_motivo': True,
    })