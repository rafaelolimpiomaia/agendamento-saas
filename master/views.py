from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import SuperAdminUser, LogAdministrativo, StatusSalao
from agendamento.models import Tenant
from django.utils import timezone
from agendamento.models import CodigoConvite, Cliente, Agendamento
from .decorators import super_admin_required
from django.db.models import Q


def master_login(request):
    if request.session.get('master_admin_id'):
        return redirect('master_dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        senha    = request.POST.get('senha', '').strip()

        try:
            admin = SuperAdminUser.objects.get(username=username, ativo=True)
        except SuperAdminUser.DoesNotExist:
            messages.error(request, 'Credenciais inválidas.')
            return render(request, 'master/login.html')

        if not admin.checar_senha(senha):
            messages.error(request, 'Credenciais inválidas.')
            return render(request, 'master/login.html')

        # Sessão própria — não usa request.user do Django
        request.session['master_admin_id'] = admin.id
        request.session.set_expiry(60 * 60 * 8)  # 8 horas

        admin.ultimo_login = timezone.now()
        admin.save(update_fields=['ultimo_login'])

        LogAdministrativo.objects.create(
            super_admin=admin,
            acao='login',
            detalhes=f'Login realizado às {timezone.now():%d/%m/%Y %H:%M}',
        )

        return redirect('master_dashboard')

    return render(request, 'master/login.html')


def master_logout(request):
    request.session.pop('master_admin_id', None)
    return redirect('master_login')

@super_admin_required
def codigos_ativacao(request):
    if request.method == 'POST':
        quantidade = int(request.POST.get('quantidade', 1))
        quantidade = max(1, min(quantidade, 50))  # limite de segurança

        novos = []
        for _ in range(quantidade):
            c = CodigoConvite.gerar()
            novos.append(c.codigo)

        LogAdministrativo.objects.create(
            super_admin=request.super_admin,
            acao='codigo',
            detalhes=f'{quantidade} código(s) gerado(s): {", ".join(novos)}',
        )
        messages.success(request, f'{quantidade} código(s) gerado(s) com sucesso.')
        return redirect('master_codigos_ativacao')

    codigos = CodigoConvite.objects.select_related('usado_por').order_by('-criado_em')

    return render(request, 'master/codigos_ativacao.html', {
        'codigos': codigos,
        'total_disponiveis': codigos.filter(usado=False).count(),
        'total_usados': codigos.filter(usado=True).count(),
    })

@super_admin_required
def excluir_salao(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)

    if request.method == 'POST':
        confirmacao = request.POST.get('confirmacao', '').strip()

        if confirmacao != tenant.slug:
            messages.error(request, 'Confirmação incorreta. Digite o slug exato do salão.')
            return redirect('master_excluir_salao', tenant_id=tenant.id)

        tenant.ativo = False
        tenant.excluido_em = timezone.now()
        tenant.save()

        status_admin, _ = StatusSalao.objects.get_or_create(tenant=tenant)
        status_admin.status = 'cancelado'
        status_admin.save()

        LogAdministrativo.objects.create(
            super_admin=request.super_admin,
            tenant=tenant,
            acao='excluir',
            detalhes=f'Soft delete executado em {timezone.now():%d/%m/%Y %H:%M}',
        )

        messages.success(request, f'Salão "{tenant.nome}" foi excluído (soft delete).')
        return redirect('master_listar_saloes')

    return render(request, 'master/confirmar_acao.html', {
        'tenant': tenant,
        'acao': 'excluir',
        'titulo': 'Excluir salão permanentemente?',
        'descricao': 'Esta ação marca o salão como excluído e desativa o acesso. Os dados são preservados para fins de auditoria. Para confirmar, digite o slug do salão abaixo.',
        'pedir_confirmacao_slug': True,
    })

@super_admin_required
def master_dashboard(request):
    total_saloes      = Tenant.objects.count()
    saloes_ativos     = StatusSalao.objects.filter(status='ativo').count()
    saloes_teste      = StatusSalao.objects.filter(status='teste').count()
    saloes_congelados = StatusSalao.objects.filter(status='congelado').count()
    saloes_suspensos  = StatusSalao.objects.filter(status='suspenso').count()
    total_clientes    = Cliente.objects.count()
    total_agendamentos = Agendamento.objects.count()
    ultimos_saloes    = Tenant.objects.order_by('-criado_em')[:5]
    ultimas_acoes     = LogAdministrativo.objects.select_related('tenant', 'super_admin')[:8]
    codigos_disponiveis = CodigoConvite.objects.filter(usado=False).count()
    codigos_usados    = CodigoConvite.objects.filter(usado=True).count()

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

    tenants = Tenant.objects.all()

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

    return render(request, 'master/detalhes_salao.html', {
        'tenant': tenant,
        'status_admin': status_admin,
        'total_clientes': Cliente.objects.filter(tenant=tenant).count(),
        'total_agendamentos': Agendamento.objects.filter(tenant=tenant).count(),
        'total_servicos': tenant.servicos.count(),
        'logs': LogAdministrativo.objects.filter(tenant=tenant)[:15],
    })


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

        # Reativa o tenant caso estivesse suspenso
        tenant.ativo = True
        tenant.save()

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
        'descricao': 'Nem admin nem clientes conseguirão acessar o sistema.',
        'pedir_motivo': True,
    })