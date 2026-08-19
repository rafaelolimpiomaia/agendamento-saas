from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .models import Cliente, Agendamento, Servico, NotificacaoExclusao, ConfiguracaoSalao, HorarioFuncionamento, PeriodoBloqueio, PedidoReserva, SlotReservado, Pagamento
from .forms import AgendamentoForm, IdentificarUsuarioForm , RedefinirSenhaForm, AgendamentoManualForm, ConfiguracaoSalaoForm
from datetime import datetime, timedelta, date
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.contrib.admin.views.decorators import staff_member_required
from collections import defaultdict
import json, re
from django.db import IntegrityError, transaction
from django.http import JsonResponse
import json as _json
from .models import HorarioBloqueado
from django.utils import timezone
from decimal import Decimal
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import logging
from .utils import (
    gerar_horarios,
    requer_horario_duplo,
    get_proximo_horario,
    is_excecao_almoco,
    is_horario_dentro_24h,
    TODOS_HORARIOS,
)


from agendamento.security import (
    rate_limit, calcular_valor_pedido, validar_valor_pagamento,
    pagamento_ja_processado, marcar_pagamento_processado,
    validar_webhook_mercadopago, adquirir_lock_slot, liberar_lock_slot,)


from django.contrib import messages
from decimal import Decimal
import calendar
from django.http import JsonResponse


from datetime import time as _time

def gerar_horarios_do_dia():
    horarios = []
    atual = datetime.combine(date.today(), _time(6, 0))
    fim = datetime.combine(date.today(), _time(23, 30))
    while atual <= fim:
        horarios.append(atual.strftime('%H:%M'))
        atual += timedelta(minutes=30)
    horarios.append('00:00')
    return horarios



STATUS_VALIDOS = {'presente', 'ausente', 'pendente'}


# ── SEGURANÇA: verifica que o staff logado é admin DESTE tenant ───────────────
def _verificar_admin_do_tenant(request):
    """
    Retorna True se o usuário logado é o admin do tenant atual.
    Impede que admin de outro salão acesse este painel.
    Superusers Django têm acesso total (para manutenção).
    """
    if request.user.is_superuser:
        return True
    if not request.user.is_staff:
        return False
    tenant = request.tenant
    # Verifica se este usuário é o admin vinculado ao tenant atual
    return tenant.admin_id == request.user.id


def admin_do_tenant_required(view_func):
    """
    Decorator que combina staff_member_required com verificação de tenant.
    Substitui @staff_member_required nas views de admin.
    """
    @staff_member_required
    def wrapper(request, *args, **kwargs):
        if not _verificar_admin_do_tenant(request):
            messages.error(request, 'Você não tem permissão para acessar este painel.')
            return redirect('login', tenant_slug=request.tenant.slug)
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

# ─────────────────────────────────────────────────────────────────────────────

@admin_do_tenant_required
def criar_servico(request, tenant_slug=None):
    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        descricao = request.POST.get("descricao", "").strip()
        preco = request.POST.get("preco", "").strip()
        duracao = request.POST.get("duracao_minutos", "").strip()
        horario_duplo = request.POST.get("horario_duplo") == "on"

        if not nome or not preco or not duracao:
            return render(request, "admin/criar_servico.html", {
                "erro": "Preencha todos os campos obrigatórios."
            })

        try:
            preco = float(preco)
            duracao = int(duracao)
        except ValueError:
            return render(request, "admin/criar_servico.html", {
                "erro": "Preço e duração devem ser numéricos.",
            })

        Servico.objects.create(
            tenant=request.tenant,
            nome=nome,
            descricao=descricao,
            preco=preco,
            duracao_minutos=duracao,
            horario_duplo=horario_duplo,
        )

        return redirect('listar_servicos', tenant_slug=request.tenant.slug)

    return render(request, "admin/criar_servico.html")


@admin_do_tenant_required
def listar_servicos(request, tenant_slug=None):
    servicos = Servico.objects.filter(tenant=request.tenant)
    return render(request, "admin/listar_servicos.html", {
        "servicos": servicos,
    })


@admin_do_tenant_required
def editar_servico(request, tenant_slug=None, id=None):
    servico = get_object_or_404(Servico, tenant=request.tenant, id=id)

    if request.method == "POST":
        servico.nome = request.POST.get("nome")
        servico.descricao = request.POST.get("descricao")
        servico.preco = request.POST.get("preco")
        servico.duracao_minutos = request.POST.get("duracao_minutos")

        novo_duplo = request.POST.get("horario_duplo") == "on"
        era_duplo = servico.horario_duplo

        servico.horario_duplo = novo_duplo
        servico.save()

        hoje = date.today()
        agendamentos_futuros = Agendamento.objects.filter(
            tenant=request.tenant,
            servico=servico,
            data__gte=hoje
        )

        for ag in agendamentos_futuros:
            horario_str = ag.horario.strftime("%H:%M")

            if is_excecao_almoco(horario_str):
                continue

            horarios_do_dia = gerar_horarios(ag.data, request.tenant)
            proximo = get_proximo_horario(horario_str, horarios_do_dia)

            if proximo is None:
                continue

            proximo_time = datetime.strptime(proximo, "%H:%M").time()

            if novo_duplo and not era_duplo:
                proximo_tem_agendamento = Agendamento.objects.filter(
                    tenant=request.tenant,
                    data=ag.data,
                    horario=proximo_time
                ).exists()
                if not proximo_tem_agendamento:
                    HorarioBloqueado.objects.update_or_create(
                        tenant=request.tenant,
                        data=ag.data,
                        horario=proximo_time,
                        defaults={"tipo": "bloqueio"}
                    )

            elif era_duplo and not novo_duplo:
                HorarioBloqueado.objects.filter(
                    tenant=request.tenant,
                    data=ag.data,
                    horario=proximo_time,
                    tipo="bloqueio"
                ).delete()

        return redirect('listar_servicos', tenant_slug=request.tenant.slug)

    return render(request, "admin/editar_servico.html", {
        "servico": servico,
    })


@admin_do_tenant_required
def excluir_servico(request, tenant_slug=None, id=None):
    servico = get_object_or_404(Servico, tenant=request.tenant, id=id)

    if request.method == "POST":
        servico.delete()
        return redirect('listar_servicos', tenant_slug=request.tenant.slug)

    return render(request, "admin/confirmar_exclusao_servico.html", {
        "servico": servico,
    })

@admin_do_tenant_required
def agendamentos_hoje(request, tenant_slug=None):
    hoje = date.today()
    agendamentos = Agendamento.objects.filter(
        tenant=request.tenant,
        data=hoje)

    return render(request, "admin/relatorio_hoje.html", {
        "agendamentos": agendamentos,
    })

@admin_do_tenant_required
def configurar_horarios(request, tenant_slug=None):
    """
    Aba de configuração de horários de funcionamento.
    Salva os horários selecionados por dia da semana e gerencia períodos de bloqueio.
    """
    tenant = request.tenant

    DIAS = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]

    # ── POST: salvar horários ─────────────────────────────────────────────────
    if request.method == 'POST' and 'salvar_horarios' in request.POST:
        # Apaga todos os horários atuais do tenant e recria
        HorarioFuncionamento.objects.filter(tenant=tenant).delete()

        for dia_num, _ in DIAS:
            horarios_selecionados = request.POST.getlist(f'dia_{dia_num}')
            for h_str in horarios_selecionados:
                try:
                    h_time = datetime.strptime(h_str, "%H:%M").time()
                    HorarioFuncionamento.objects.create(
                        tenant=tenant,
                        dia_semana=dia_num,
                        horario=h_time,
                    )
                except ValueError:
                    pass

        messages.success(request, 'Horários de funcionamento salvos com sucesso!')
        return redirect('configurar_horarios', tenant_slug=tenant.slug)

    # ── POST: adicionar período de bloqueio ───────────────────────────────────
    if request.method == 'POST' and 'adicionar_bloqueio' in request.POST:
        data_inicio = request.POST.get('data_inicio')
        data_fim    = request.POST.get('data_fim')
        motivo      = request.POST.get('motivo', '').strip()

        if data_inicio and data_fim and data_inicio <= data_fim:
            PeriodoBloqueio.objects.create(
                tenant=tenant,
                data_inicio=data_inicio,
                data_fim=data_fim,
                motivo=motivo,
            )
            messages.success(request, 'Período de bloqueio adicionado.')
        else:
            messages.error(request, 'Datas inválidas. A data de início deve ser anterior à data de fim.')

        return redirect('configurar_horarios', tenant_slug=tenant.slug)

    # ── POST: remover período de bloqueio ─────────────────────────────────────
    if request.method == 'POST' and 'remover_bloqueio' in request.POST:
        bloqueio_id = request.POST.get('bloqueio_id')
        PeriodoBloqueio.objects.filter(id=bloqueio_id, tenant=tenant).delete()
        messages.success(request, 'Período de bloqueio removido.')
        return redirect('configurar_horarios', tenant_slug=tenant.slug)

    # ── GET: monta contexto ───────────────────────────────────────────────────
    # Horários configurados por dia {dia_num: set("HH:MM")}
    horarios_por_dia = {dia: set() for dia, _ in DIAS}
    for hf in HorarioFuncionamento.objects.filter(tenant=tenant):
        horarios_por_dia[hf.dia_semana].add(hf.horario.strftime("%H:%M"))

    periodos_bloqueio = PeriodoBloqueio.objects.filter(tenant=tenant)

    return render(request, 'admin/configurar_horarios.html', {
        'todos_horarios': TODOS_HORARIOS,
        'dias': DIAS,
        'horarios_por_dia': horarios_por_dia,
        'periodos_bloqueio': periodos_bloqueio,
    })


@admin_do_tenant_required
def remover_periodo_bloqueio(request, tenant_slug=None, bloqueio_id=None):
    PeriodoBloqueio.objects.filter(id=bloqueio_id, tenant=request.tenant).delete()
    messages.success(request, 'Período removido.')
    return redirect('configurar_horarios', tenant_slug=request.tenant.slug)

@admin_do_tenant_required
def calendario_admin(request, tenant_slug=None):
    hoje = date.today()
    return render(request, 'admin/calendario_admin.html', {
        'hoje': hoje.isoformat(),
    })


@admin_do_tenant_required
def api_calendario_dados(request, tenant_slug=None):
    try:
        ano = int(request.GET.get('ano', date.today().year))
        mes = int(request.GET.get('mes', date.today().month))
    except (ValueError, TypeError):
        return JsonResponse({'erro': 'Parâmetros inválidos'}, status=400)

    primeiro_dia = date(ano, mes, 1)
    ultimo_dia = date(ano, mes, calendar.monthrange(ano, mes)[1])

    agendamentos_mes = (
        Agendamento.objects
        .filter(tenant=request.tenant, data__gte=primeiro_dia, data__lte=ultimo_dia)
        .select_related('cliente__id_usuario', 'servico')
        .order_by('data', 'horario')
    )

    bloqueios_mes = (
        HorarioBloqueado.objects
        .filter(
            tenant=request.tenant,
            data__gte=primeiro_dia, data__lte=ultimo_dia)
    )

    agenda_idx = {}
    contagem_por_dia = defaultdict(int)

    for ag in agendamentos_mes:
        data_str = ag.data.isoformat()
        hora_str = ag.horario.strftime('%H:%M')
        contagem_por_dia[data_str] += 1
        agenda_idx[(data_str, hora_str)] = {
            'id': ag.id,
            'cliente': ag.nome_cliente,
            'telefone': ag.telefone_cliente,
            'servico': ag.servico.nome if ag.servico else '—',
            'status': ag.status,
            'descricao': ag.descricao,
            'origem': ag.origem,
        }

    bloqueio_idx = {}
    dias_bloqueados = set()

    for b in bloqueios_mes:
        data_str = b.data.isoformat()
        if b.horario is None:
            if b.tipo == 'bloqueio':
                dias_bloqueados.add(data_str)
        else:
            hora_str = b.horario.strftime('%H:%M')
            bloqueio_idx[(data_str, hora_str)] = b.tipo

    dias = {}
    delta = timedelta(days=1)
    dia_cursor = primeiro_dia

    while dia_cursor <= ultimo_dia:
        data_str = dia_cursor.isoformat()
        horarios_do_dia = gerar_horarios(dia_cursor, request.tenant)
        dia_bloqueado = data_str in dias_bloqueados

        slots = []
        for hora_str in horarios_do_dia:
            ag = agenda_idx.get((data_str, hora_str))
            tipo_bloqueio = bloqueio_idx.get((data_str, hora_str))

            if ag:
                status_slot = 'ocupado'
            elif dia_bloqueado:
                if tipo_bloqueio == 'liberado':
                    status_slot = 'livre'
                else:
                    status_slot = 'bloqueado'
            elif tipo_bloqueio == 'bloqueio':
                status_slot = 'bloqueado'
            else:
                status_slot = 'livre'

            slots.append({
                'horario': hora_str,
                'status': status_slot,
                'agendamento': ag,
            })

        total_agendamentos = contagem_por_dia.get(data_str, 0)
        total_horarios = len(horarios_do_dia)

        dias[data_str] = {
            'total': total_agendamentos,
            'total_horarios': total_horarios,
            'fechado': total_horarios == 0,
            'dia_bloqueado': dia_bloqueado,
            'horarios': slots,
        }

        dia_cursor += delta

    return JsonResponse({
        'ano': ano,
        'mes': mes,
        'dias': dias,
    })

@admin_do_tenant_required
def relatorio_31_dias(request, tenant_slug=None):
    hoje = timezone.localdate()
    inicio = hoje - timedelta(days=30)

    agendamentos = Agendamento.objects.filter(
        tenant=request.tenant,
        data__range=[inicio, hoje],
        status='presente'
    ).select_related('servico').order_by('data')

    total = sum(ag.servico.preco for ag in agendamentos)

    faturamento_por_dia = defaultdict(Decimal)

    for ag in agendamentos:
        faturamento_por_dia[ag.data.isoformat()] += ag.servico.preco

    datas_ordenadas = []
    valores_ordenados = []

    for i in range(0, 31):
        dia = inicio + timedelta(days=i)
        dia_str = dia.isoformat()

        datas_ordenadas.append(dia.strftime("%d/%m"))
        valores_ordenados.append(float(round(faturamento_por_dia.get(dia_str, Decimal('0')), 2)))

    servicos = Servico.objects.filter(tenant=request.tenant)
    servicos_dict = {s.nome: Decimal('0') for s in servicos}

    for ag in agendamentos:
        servicos_dict[ag.servico.nome] += ag.servico.preco

    servicos_dict = {k: v for k, v in servicos_dict.items() if v > 0}

    servicos_labels = list(servicos_dict.keys())
    servicos_valores = [float(v) for v in servicos_dict.values()]

    dias_semana = {
        "Monday": 0, "Tuesday": 0, "Wednesday": 0, "Thursday": 0,
        "Friday": 0, "Saturday": 0, "Sunday": 0,
    }

    for ag in agendamentos:
        dia = ag.data.strftime("%A")
        dias_semana[dia] += 1

    traducao = {
        "Monday": "Seg", "Tuesday": "Ter", "Wednesday": "Qua",
        "Thursday": "Qui", "Friday": "Sex", "Saturday": "Sáb", "Sunday": "Dom",
    }

    dias_labels = []
    dias_valores = []

    for dia, valor in dias_semana.items():
        dias_labels.append(traducao[dia])
        dias_valores.append(valor)

    servico_top = max(servicos_dict, key=servicos_dict.get) if servicos_dict else "Nenhum"

    total_agendamentos = Agendamento.objects.filter(
        tenant=request.tenant,
        data__range=[inicio, hoje]
    ).count()

    total_ausentes = Agendamento.objects.filter(
        tenant=request.tenant,
        data__range=[inicio, hoje],
        status='ausente'
    ).count()

    taxa_ausencia = 0
    if total_agendamentos > 0:
        taxa_ausencia = (total_ausentes / total_agendamentos) * 100

    return render(request, "admin/relatorio_31.html", {
        "agendamentos": agendamentos,
        "faturamento_total": total,
        "labels_faturamento": json.dumps(datas_ordenadas),
        "dados_faturamento": json.dumps(valores_ordenados),
        "labels_servicos": json.dumps(servicos_labels),
        "dados_servicos": json.dumps(servicos_valores),
        "labels_semana": json.dumps(dias_labels),
        "dados_semana": json.dumps(dias_valores),
        "servico_mais_lucrativo": servico_top,
        "total_agendamentos": total_agendamentos,
        "taxa_ausencia": round(taxa_ausencia, 1)
    })

@admin_do_tenant_required
def personalizar_salao(request, tenant_slug=None):
    tenant = request.tenant
    config, _ = ConfiguracaoSalao.objects.get_or_create(tenant=tenant)

    DIAS = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]

    # ── POST: salvar configurações gerais ─────────────────────────────────────
    if request.method == 'POST' and 'salvar_config' in request.POST:
        form = ConfiguracaoSalaoForm(request.POST)
        if form.is_valid():
            config.nome_exibicao = form.cleaned_data['nome_exibicao']
            config.tipo_negocio  = form.cleaned_data['tipo_negocio']
            config.telefone      = form.cleaned_data['telefone']
            config.publico       = form.cleaned_data['publico']
            config.endereco      = form.cleaned_data['endereco']
            config.instagram     = form.cleaned_data['instagram']
            config.cor_primaria  = form.cleaned_data['cor_primaria'] or '#0d6efd'
            config.save()
            messages.success(request, 'Configurações salvas com sucesso!')
        return redirect('personalizar_salao', tenant_slug=tenant.slug)

    # ── POST: salvar horários ─────────────────────────────────────────────────
    if request.method == 'POST' and 'salvar_horarios' in request.POST:
        HorarioFuncionamento.objects.filter(tenant=tenant).delete()
        for dia_num, _ in DIAS:
            for h_str in request.POST.getlist(f'dia_{dia_num}'):
                try:
                    from datetime import datetime as dt
                    h_time = dt.strptime(h_str, "%H:%M").time()
                    HorarioFuncionamento.objects.create(
                        tenant=tenant,
                        dia_semana=dia_num,
                        horario=h_time,
                    )
                except ValueError:
                    pass
        messages.success(request, 'Horários de funcionamento salvos com sucesso!')
        return redirect('personalizar_salao', tenant_slug=tenant.slug)

    # ── POST: adicionar período de bloqueio ───────────────────────────────────
    if request.method == 'POST' and 'adicionar_bloqueio' in request.POST:
        data_inicio = request.POST.get('data_inicio')
        data_fim    = request.POST.get('data_fim')
        motivo      = request.POST.get('motivo', '').strip()
        if data_inicio and data_fim and data_inicio <= data_fim:
            PeriodoBloqueio.objects.create(
                tenant=tenant,
                data_inicio=data_inicio,
                data_fim=data_fim,
                motivo=motivo,
            )
            messages.success(request, 'Período de bloqueio adicionado.')
        else:
            messages.error(request, 'Datas inválidas.')
        return redirect('personalizar_salao', tenant_slug=tenant.slug)

    # ── POST: remover período de bloqueio ─────────────────────────────────────
    if request.method == 'POST' and 'remover_bloqueio' in request.POST:
        bloqueio_id = request.POST.get('bloqueio_id')
        PeriodoBloqueio.objects.filter(id=bloqueio_id, tenant=tenant).delete()
        messages.success(request, 'Período de bloqueio removido.')
        return redirect('personalizar_salao', tenant_slug=tenant.slug)

    # ── GET ───────────────────────────────────────────────────────────────────
    form = ConfiguracaoSalaoForm(initial={
        'nome_exibicao': config.nome_exibicao,
        'tipo_negocio':  config.tipo_negocio,
        'telefone':      config.telefone,
        'publico':       config.publico,
        'endereco':      config.endereco,
        'instagram':     config.instagram,
        'cor_primaria':  config.cor_primaria,
    })

    # Retorna strings "HH:MM" para comparação no JS
    horarios_por_dia = {}
    for dia_num, _ in DIAS:
        horarios_por_dia[dia_num] = set(
            hf.strftime("%H:%M")
            for hf in HorarioFuncionamento.objects.filter(
                tenant=tenant, dia_semana=dia_num
            ).values_list('horario', flat=True)
        )

    # Serializa para JSON para uso no template via JavaScript
    horarios_json = _json.dumps({
        str(dia_num): list(horarios_por_dia[dia_num])
        for dia_num, _ in DIAS
    })

    periodos_bloqueio = PeriodoBloqueio.objects.filter(tenant=tenant)

    return render(request, 'admin/personalizar_salao.html', {
        'form': form,
        'config': config,
        'todos_horarios': TODOS_HORARIOS,
        'dias': DIAS,
        'horarios_json': horarios_json,
        'periodos_bloqueio': periodos_bloqueio,
    })

@admin_do_tenant_required
def painel_admin(request, tenant_slug=None):
    return render(request, 'admin/painel_admin.html')


@admin_do_tenant_required
def atualizar_status(request, tenant_slug=None, id=None, status=None):
    if status not in STATUS_VALIDOS:
        messages.error(request, "Status inválido.")
        return redirect('agendamentos_hoje', tenant_slug=request.tenant.slug)

    ag = get_object_or_404(Agendamento, tenant=request.tenant, id=id)
    ag.status = status
    ag.save()
    return redirect('agendamentos_hoje', tenant_slug=request.tenant.slug)


@admin_do_tenant_required
def proximos_agendamentos(request, tenant_slug=None):
    data = request.GET.get("data")
    data_convertida = converter_data(data) if data else None
    hoje = date.today()

    if data_convertida:
        agendamentos = Agendamento.objects.filter(
            tenant=request.tenant,
            data=data_convertida
        ).order_by('data', 'horario')
    else:
        agendamentos = Agendamento.objects.filter(
            tenant=request.tenant,
            data__gte=hoje
        ).order_by('data', 'horario')

    return render(request, 'admin/proximos_agendamentos.html', {
        'agendamentos': agendamentos,
        'data': data
    })


@admin_do_tenant_required
def excluir_agendamento_admin(request, tenant_slug=None, id=None):
    agendamento = get_object_or_404(Agendamento, tenant=request.tenant, id=id)

    if request.method == 'POST':
        cliente = agendamento.cliente
        servico_nome = agendamento.servico.nome if agendamento.servico else 'Serviço não informado'
        data_ag = agendamento.data
        horario_ag = agendamento.horario

        if agendamento.servico and requer_horario_duplo(agendamento.servico):
            horario_str = agendamento.horario.strftime("%H:%M")
            if not is_excecao_almoco(horario_str):
                horarios_do_dia = gerar_horarios(agendamento.data, agendamento.tenant)
                proximo = get_proximo_horario(horario_str, horarios_do_dia)
                if proximo is not None:
                    proximo_time = datetime.strptime(proximo, "%H:%M").time()
                    HorarioBloqueado.objects.filter(
                        tenant=request.tenant,
                        data=agendamento.data,
                        horario=proximo_time,
                        tipo="bloqueio"
                    ).delete()

        agendamento.delete()

        if cliente:
            NotificacaoExclusao.objects.create(
                cliente=cliente,
                servico_nome=servico_nome,
                data_agendamento=data_ag,
                horario_agendamento=horario_ag,
            )

        messages.success(request, 'Agendamento excluído e cliente notificada.')
        return redirect('proximos_agendamentos', tenant_slug=request.tenant.slug)

    return render(request, 'admin/confirmar_exclusao_agendamento.html', {
        'agendamento': agendamento
    })


@login_required
def marcar_notificacao_lida(request, tenant_slug=None, notif_id=None):
    if request.method == 'POST':
        cliente = get_object_or_404(Cliente, tenant=request.tenant, id_usuario=request.user)
        notif = get_object_or_404(NotificacaoExclusao, id=notif_id, cliente=cliente)
        notif.visualizado = True
        notif.save()
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False}, status=405)


def converter_data(data):
    if not data:
        return None

    formatos = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]

    for formato in formatos:
        try:
            return datetime.strptime(data, formato).date()
        except ValueError:
            continue

    return None


@admin_do_tenant_required
def gerenciar_horarios(request, tenant_slug=None):
    data = request.GET.get("data")
    data_formatada = converter_data(data)

    horarios = gerar_horarios(data_formatada, request.tenant)

    bloqueados = []
    horarios_liberados = []
    dia_bloqueado = False

    if data_formatada:
        bloqueios = HorarioBloqueado.objects.filter(
            tenant=request.tenant,
            data=data_formatada
        )

        bloqueados = [
            b.horario.strftime("%H:%M")
            for b in bloqueios
            if b.tipo == "bloqueio" and b.horario
        ]

        horarios_liberados = [
            b.horario.strftime("%H:%M")
            for b in bloqueios
            if b.tipo == "liberado" and b.horario
        ]

        dia_bloqueado = bloqueios.filter(
            horario__isnull=True,
            tipo="bloqueio"
        ).exists()

    return render(request, "admin/gerenciar_horarios.html", {
        "horarios": horarios,
        "data": data or "",
        "bloqueados": bloqueados,
        "horarios_liberados": horarios_liberados,
        "dia_bloqueado": dia_bloqueado
    })


@admin_do_tenant_required
def bloquear_horario(request, tenant_slug=None):
    if request.method == "POST":
        data = request.POST.get("data")
        horario = request.POST.get("horario")
        data_formatada = converter_data(data)

        if data_formatada and horario and data_formatada >= date.today():
            horario_formatado = datetime.strptime(horario, "%H:%M").time()

            HorarioBloqueado.objects.filter(
                tenant=request.tenant,
                data=data_formatada,
                horario=horario_formatado,
                tipo="liberado"
            ).delete()

            HorarioBloqueado.objects.update_or_create(
                tenant=request.tenant,
                data=data_formatada,
                horario=horario_formatado,
                defaults={"tipo": "bloqueio"}
            )

        return redirect(f"/{request.tenant.slug}/gerenciar-horarios/?data={data}")

    return redirect(f"/{request.tenant.slug}/gerenciar-horarios/")


@admin_do_tenant_required
def desbloquear_horario(request, tenant_slug=None):
    if request.method == "POST":
        data = request.POST.get("data")
        horario = request.POST.get("horario")
        data_formatada = converter_data(data)

        if data_formatada and horario and data_formatada >= date.today():
            horario_formatado = datetime.strptime(horario, "%H:%M").time()

            HorarioBloqueado.objects.filter(
                tenant=request.tenant,
                data=data_formatada,
                horario=horario_formatado,
                tipo="bloqueio"
            ).delete()

        return redirect(f"/{request.tenant.slug}/gerenciar-horarios/?data={data}")

    return redirect(f"/{request.tenant.slug}/gerenciar-horarios/")


@admin_do_tenant_required
def liberar_horario(request, tenant_slug=None):
    if request.method == "POST":
        data = request.POST.get("data")
        horario = request.POST.get("horario")
        data_formatada = converter_data(data)

        if data_formatada and horario and data_formatada >= date.today():
            horario_formatado = datetime.strptime(horario, "%H:%M").time()

            HorarioBloqueado.objects.filter(
                tenant=request.tenant,
                data=data_formatada,
                horario=horario_formatado,
                tipo="bloqueio"
            ).delete()

            HorarioBloqueado.objects.update_or_create(
                tenant=request.tenant,
                data=data_formatada,
                horario=horario_formatado,
                defaults={"tipo": "liberado"}
            )

        return redirect(f"/{request.tenant.slug}/gerenciar-horarios/?data={data}")

    return redirect(f"/{request.tenant.slug}/gerenciar-horarios/")


@admin_do_tenant_required
def bloquear_dia(request, tenant_slug=None):
    if request.method == "POST":
        data = request.POST.get("data")
        data_formatada = converter_data(data)

        if data_formatada and data_formatada >= date.today():
            HorarioBloqueado.objects.update_or_create(
                tenant=request.tenant,
                data=data_formatada,
                horario=None,
                defaults={"tipo": "bloqueio"}
            )

        return redirect(f"/{request.tenant.slug}/gerenciar-horarios/?data={data}")

    return redirect(f"/{request.tenant.slug}/gerenciar-horarios/")


@admin_do_tenant_required
def desbloquear_dia(request, tenant_slug=None):
    if request.method == "POST":
        data = request.POST.get("data")
        data_formatada = converter_data(data)

        if data_formatada and data_formatada >= date.today():
            HorarioBloqueado.objects.filter(
                tenant=request.tenant,
                data=data_formatada,
                horario=None,
                tipo="bloqueio"
            ).delete()

        return redirect(f"/{request.tenant.slug}/gerenciar-horarios/?data={data}")

    return redirect(f"/{request.tenant.slug}/gerenciar-horarios/")


@admin_do_tenant_required
def remover_excecao(request, tenant_slug=None):
    if request.method == "POST":
        data = request.POST.get("data")
        horario = request.POST.get("horario")
        data_formatada = converter_data(data)

        if data_formatada and horario:
            horario_formatado = datetime.strptime(horario, "%H:%M").time()

            HorarioBloqueado.objects.filter(
                tenant=request.tenant,
                data=data_formatada,
                horario=horario_formatado,
                tipo="liberado"
            ).delete()

        return redirect(f"/{request.tenant.slug}/gerenciar-horarios/?data={data}")

    return redirect(f"/{request.tenant.slug}/gerenciar-horarios/")

# ── GESTÃO DE CLIENTES (admin) ────────────────────────────────────────────────

@admin_do_tenant_required
def listar_clientes(request, tenant_slug=None):
    q = request.GET.get('q', '').strip()

    clientes_qs = Cliente.objects.filter(
        tenant=request.tenant
    ).select_related('id_usuario')

    if q:
        clientes_qs = clientes_qs.filter(id_usuario__username__icontains=q)

    clientes_qs = clientes_qs.order_by('id_usuario__username')

    clientes_data = []
    for cliente in clientes_qs:
        total_agendamentos = Agendamento.objects.filter(
            tenant=request.tenant,
            cliente=cliente).count()
        total_ausencias = Agendamento.objects.filter(
            tenant=request.tenant,
            cliente=cliente, status='ausente').count()
        clientes_data.append({
            'cliente': cliente,
            'total_agendamentos': total_agendamentos,
            'total_ausencias': total_ausencias,
        })

    return render(request, 'admin/listar_clientes.html', {
        'clientes_data': clientes_data,
        'q': q,
        'total_clientes': clientes_qs.count(),
    })


@admin_do_tenant_required
def bloquear_cliente(request, tenant_slug=None, user_id=None):
    if request.method == 'POST':
        cliente = get_object_or_404(Cliente, tenant=request.tenant, id_usuario__id=user_id)
        if not cliente.id_usuario.is_staff:
            cliente.bloqueado = True
            cliente.save()
            messages.success(
                request,
                f'Cliente "{cliente.id_usuario.username}" foi bloqueado com sucesso.'
            )
        else:
            messages.error(request, 'Não é possível bloquear um administrador.')
    return redirect('listar_clientes', tenant_slug=request.tenant.slug)


@admin_do_tenant_required
def desbloquear_cliente(request, tenant_slug=None, user_id=None):
    if request.method == 'POST':
        cliente = get_object_or_404(Cliente, tenant=request.tenant, id_usuario__id=user_id)
        cliente.bloqueado = False
        cliente.save()
        messages.success(
            request,
            f'Cliente "{cliente.id_usuario.username}" foi desbloqueado com sucesso.'
        )
    return redirect('listar_clientes', tenant_slug=request.tenant.slug)


@admin_do_tenant_required
def excluir_cliente(request, tenant_slug=None, user_id=None):
    user = get_object_or_404(User, id=user_id, is_staff=False)

    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f'Conta de "{username}" foi excluída com sucesso.')
        return redirect('listar_clientes', tenant_slug=request.tenant.slug)

    cliente = get_object_or_404(Cliente, tenant=request.tenant, id_usuario=user)
    total_agendamentos = Agendamento.objects.filter(
        tenant=request.tenant,
        cliente=cliente).count()
    return render(request, 'admin/confirmar_exclusao_cliente.html', {
        'user': user,
        'cliente': cliente,
        'total_agendamentos': total_agendamentos,
    })

@admin_do_tenant_required
def agendamento_manual(request, tenant_slug=None):
    data_str = request.GET.get('data') or request.POST.get('data') or ''
    data_convertida = converter_data(data_str) if data_str else None

    horarios_do_dia = gerar_horarios(data_convertida, request.tenant)

    horarios_ocupados = []
    bloqueados_lista = []

    bloqueios = (
        HorarioBloqueado.objects.filter(
            tenant=request.tenant,
            data=data_convertida)
        if data_convertida
        else HorarioBloqueado.objects.none()
    )

    dia_bloqueado = bloqueios.filter(horario__isnull=True, tipo='bloqueio').exists()

    if data_convertida:
        horarios_ocupados = list(
            Agendamento.objects.filter(
                tenant=request.tenant,
                data=data_convertida)
            .values_list('horario', flat=True)
        )
        horarios_ocupados = [h.strftime('%H:%M') for h in horarios_ocupados]

    for h in horarios_do_dia:
        horario_time = datetime.strptime(h, '%H:%M').time()

        bloq_manual = bloqueios.filter(horario=horario_time, tipo='bloqueio').exists()
        lib_manual  = bloqueios.filter(horario=horario_time, tipo='liberado').exists()

        if (dia_bloqueado and not lib_manual) or bloq_manual or h in horarios_ocupados:
            bloqueados_lista.append(h)

    horarios_disponiveis = [h for h in horarios_do_dia if h not in bloqueados_lista]

    if request.method == 'POST':
        form = AgendamentoManualForm(
            request.POST,
            tenant=request.tenant,
            horarios_disponiveis=horarios_do_dia,
        )

        if form.is_valid():
            nome      = form.cleaned_data['nome'].strip()
            telefone  = form.cleaned_data['telefone'].strip()
            servico   = form.cleaned_data['servico']
            data      = form.cleaned_data['data']
            horario   = form.cleaned_data['horario']
            descricao = form.cleaned_data.get('descricao', '')

            if Agendamento.objects.filter(
                tenant=request.tenant,
                data=data, horario=horario).exists():
                form.add_error('horario', 'Esse horário já está ocupado.')

            elif _horario_esta_bloqueado(request.tenant, data, horario):
                form.add_error('horario', 'Este horário está bloqueado na agenda.')

            else:
                duplo = requer_horario_duplo(servico)
                if duplo:
                    horario_str = horario.strftime('%H:%M')
                    if not is_excecao_almoco(horario_str):
                        proximo = get_proximo_horario(horario_str, horarios_do_dia)
                        if proximo is not None:
                            proximo_time = datetime.strptime(proximo, '%H:%M').time()
                            proximo_ocupado = (
                                Agendamento.objects.filter(
                                    tenant=request.tenant,
                                    data=data, horario=proximo_time).exists()
                                or _horario_esta_bloqueado(request.tenant, data, proximo_time)
                            )
                            if proximo_ocupado:
                                form.add_error(
                                    'horario',
                                    f'Este serviço ocupa dois horários consecutivos '
                                    f'({horario_str} e {proximo}), '
                                    f'mas {proximo} já está ocupado. Escolha outro horário.',
                                )

            if not form.errors:
                ag = Agendamento(
                    tenant=request.tenant,
                    cliente=None,
                    servico=servico,
                    data=data,
                    horario=horario,
                    descricao=descricao,
                    origem=Agendamento.ORIGEM_MANUAL,
                    nome_manual=nome,
                    telefone_manual=telefone,
                )

                try:
                    ag.full_clean()
                    ag.save()

                    if requer_horario_duplo(servico):
                        horario_str = horario.strftime('%H:%M')
                        if not is_excecao_almoco(horario_str):
                            proximo = get_proximo_horario(horario_str, horarios_do_dia)
                            if proximo is not None:
                                proximo_time = datetime.strptime(proximo, '%H:%M').time()
                                HorarioBloqueado.objects.update_or_create(
                                    tenant=request.tenant,
                                    data=data,
                                    horario=proximo_time,
                                    defaults={'tipo': 'bloqueio'},
                                )

                    messages.success(
                        request,
                        f'Agendamento manual de {nome} registrado com sucesso '
                        f'para {data.strftime("%d/%m/%Y")} às {horario.strftime("%H:%M")}.',
                    )
                    return redirect('proximos_agendamentos', tenant_slug=request.tenant.slug)

                except ValidationError as e:
                    for field, errs in e.message_dict.items():
                        for err in errs:
                            form.add_error(None, err)

                except IntegrityError:
                    form.add_error('horario', 'Esse horário acabou de ser ocupado. Tente outro.')

    else:
        initial = {
            'data':      data_str,
            'nome':      request.GET.get('nome', ''),
            'telefone':  request.GET.get('telefone', ''),
            'servico':   request.GET.get('servico', ''),
            'descricao': request.GET.get('descricao', ''),
        }
        form = AgendamentoManualForm(
            initial=initial,
            tenant=request.tenant,
            horarios_disponiveis=horarios_do_dia,
        )

    return render(request, 'admin/agendamento_manual.html', {
        'form': form,
        'data_str': data_str,
        'horarios_do_dia': horarios_do_dia,
        'horarios_ocupados': horarios_ocupados,
        'bloqueados': bloqueados_lista,
        'horarios_disponiveis': horarios_disponiveis,
    })

# ── VIEWS DE CLIENTE ──────────────────────────────────────────────────────────

def register(request, tenant_slug=None):
    if request.method == "POST":
        username    = request.POST.get("username", "").strip()
        telefone    = request.POST.get("telefone", "").strip()
        password    = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            return render(request, 'clients/register.html', {'erro': 'As senhas não coincidem!'})

        # Backend concatena o slug — usuário só digita o nome
        username_unico = f"{username}__{request.tenant.slug}"

        if User.objects.filter(username=username_unico).exists():
            return render(request, 'clients/register.html', {'erro': 'Usuário já existe!'})

        user = User.objects.create_user(username=username_unico, password=password)

        cliente, _ = Cliente.objects.get_or_create(
            id_usuario=user,
            defaults={'tenant': request.tenant}
        )
        cliente.telefone = telefone
        cliente.save()

        return redirect('login', tenant_slug=request.tenant.slug)

    return render(request, 'clients/register.html')


def login_view(request, tenant_slug=None):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password")

        # Backend monta o username completo
        username_unico = f"{username}__{request.tenant.slug}"

        user = authenticate(request, username=username_unico, password=password)

        if user:
            login(request, user)
            if user.is_staff:
                return redirect('painel_admin', tenant_slug=request.tenant.slug)
            else:
                return redirect('home', tenant_slug=request.tenant.slug)

        return render(request, 'clients/login.html', {
            'erro': 'Login inválido! Verifique os dados da conta ou crie uma!'
        })

    return render(request, 'clients/login.html')

def logout_view(request, tenant_slug=None):
    slug = request.tenant.slug
    logout(request)
    return redirect('login', tenant_slug=slug)


def esqueci_senha(request, tenant_slug=None):
    form = IdentificarUsuarioForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        nome     = form.cleaned_data["nome"]
        telefone = form.cleaned_data["telefone"]

        # Backend monta o username completo
        username_unico = f"{nome}__{request.tenant.slug}"
        usuario = User.objects.filter(username__iexact=username_unico).first()

        def apenas_digitos(valor):
            return re.sub(r'\D', '', valor or '')

        telefone_confere = (
            usuario is not None
            and hasattr(usuario, 'cliente')
            and apenas_digitos(usuario.cliente.telefone) == apenas_digitos(telefone)
        )

        if not telefone_confere:
            form.add_error(None, "Dados não encontrados. Verifique nome e telefone.")
            return render(request, "clients/esqueci_senha.html", {"form": form})

        request.session["redefinir_nome"] = username_unico  # salva o username completo
        return redirect("redefinir_senha", tenant_slug=request.tenant.slug)

    return render(request, "clients/esqueci_senha.html", {"form": form})


def redefinir_senha(request, tenant_slug=None):
    nome = request.session.get("redefinir_nome")  # já vem com o slug

    if not nome:
        messages.error(request, "Sessão expirada. Comece novamente.")
        return redirect("esqueci_senha", tenant_slug=request.tenant.slug)

    form = RedefinirSenhaForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        nova_senha = form.cleaned_data["nova_senha"]
        usuario = User.objects.filter(username__iexact=nome).first()

        if usuario:
            usuario.set_password(nova_senha)
            usuario.save()
            del request.session["redefinir_nome"]
            messages.success(request, "Senha redefinida com sucesso! Entre com sua nova senha.")
        else:
            messages.error(request, "Usuário não encontrado.")
            return redirect("esqueci_senha", tenant_slug=request.tenant.slug)

    # Exibe o nome sem o sufixo do tenant para o usuário
    nome_exibicao = nome.split('__')[0] if '__' in nome else nome

    return render(request, "clients/redefinir_senha.html", {
        "form": form,
        "nome": nome_exibicao,
    })


@login_required
def home(request, tenant_slug=None):
    if request.user.is_staff:
        return redirect('painel_admin', tenant_slug=request.tenant.slug)

    notificacoes_pendentes = []
    try:
        cliente = Cliente.objects.get(tenant=request.tenant, id_usuario=request.user)
        notificacoes_pendentes = list(
            NotificacaoExclusao.objects.filter(cliente=cliente, visualizado=False)
            .order_by('criado_em')
        )
    except Cliente.DoesNotExist:
        pass

    return render(request, 'clients/home.html', {
        'notificacoes_pendentes': notificacoes_pendentes
    })


@login_required
def criar_agendamento(request, tenant_slug=None):
    if getattr(request, 'tenant_congelado', False):
        return render(request, 'clients/salao_congelado.html')

    if request.user.is_staff:
        return redirect('painel_admin', tenant_slug=request.tenant.slug)

    cliente, _ = Cliente.objects.get_or_create(
        id_usuario=request.user,
        defaults={'tenant': request.tenant}
    )

    if cliente.bloqueado:
        return render(request, 'clients/cliente_bloqueado.html')

    servico_id = request.session.get("servico_id")
    if not servico_id:
        return redirect("escolher_servico", tenant_slug=request.tenant.slug)

    servico = get_object_or_404(Servico, tenant=request.tenant, id=servico_id, ativo=True)

    data_selecionada = request.GET.get("data") or date.today().strftime('%d/%m/%Y')
    data_convertida = converter_data(data_selecionada)

    horarios_todos = gerar_horarios_do_dia()  # 06:00 até 00:00, de 30 em 30

    # Se a data selecionada for HOJE, remove os horários que já passaram
    if data_convertida == date.today():
        agora = timezone.localtime()
        horarios = [
            h for h in horarios_todos
            if datetime.strptime(h, '%H:%M').time() > agora.time()
        ]
    else:
        horarios = horarios_todos

    horarios_ocupados = []

    if data_convertida:
        PedidoReserva.objects.filter(
            status__in=['bloqueado', 'aguardando_pagamento'],
            expira_em__lt=timezone.now(),
        ).delete()

        slots_de_outros = SlotReservado.objects.filter(
            tenant=request.tenant, servico=servico, data=data_convertida,
        ).exclude(pedido__cliente=cliente).values_list('horario', flat=True)

        confirmados = Agendamento.objects.filter(
            tenant=request.tenant, servico=servico, data=data_convertida,
            status__in=['pendente', 'presente'],
        ).values_list('horario', flat=True)

        horarios_ocupados = [h.strftime('%H:%M') for h in slots_de_outros] + \
                            [h.strftime('%H:%M') for h in confirmados]

    preco_hora = servico.preco * (Decimal(60) / Decimal(servico.duracao_minutos))
    horarios_menos_24h = []  # regra de 24h removida — não se aplica a quadras

    # Mantém o campo de data igual estava antes (calendário funcionando)
    form = AgendamentoForm(initial={'data': data_selecionada})

    return render(request, 'clients/agendar.html', {
        'form': form,
        'horarios': horarios,
        'horarios_json': _json.dumps(horarios),
        'horarios_ocupados': horarios_ocupados,
        'horarios_ocupados_json': _json.dumps(horarios_ocupados),
        'horarios_menos_24h': horarios_menos_24h,
        'horarios_menos_24h_json': _json.dumps(horarios_menos_24h),
        'data_selecionada': data_convertida.strftime('%d/%m/%Y') if data_convertida else data_selecionada,
        'servico': servico,
        'preco_hora': preco_hora,
        'tenant_slug': request.tenant.slug,
    })

@login_required
def listar_agendamentos(request, tenant_slug=None):
    cliente, _ = Cliente.objects.get_or_create(
    id_usuario=request.user,
    defaults={'tenant': request.tenant}
)

    agendamentos = Agendamento.objects.filter(
        tenant=request.tenant, cliente=cliente).order_by('data', 'horario')

    return render(request, 'clients/lista.html', {
        'agendamentos': agendamentos
    })


@login_required
def excluir_agendamento(request, tenant_slug=None, id=None):
    cliente, _ = Cliente.objects.get_or_create(
    id_usuario=request.user,
    defaults={'tenant': request.tenant}
)

    agendamento = get_object_or_404(Agendamento, tenant=request.tenant, id=id, cliente=cliente)

    if request.method == 'POST':
        if agendamento.servico and requer_horario_duplo(agendamento.servico):
            horario_str = agendamento.horario.strftime("%H:%M")
            if not is_excecao_almoco(horario_str):
                horarios_do_dia = gerar_horarios(agendamento.data, agendamento.tenant)
                proximo = get_proximo_horario(horario_str, horarios_do_dia)
                if proximo is not None:
                    proximo_time = datetime.strptime(proximo, "%H:%M").time()
                    HorarioBloqueado.objects.filter(
                        tenant=request.tenant,
                        data=agendamento.data,
                        horario=proximo_time,
                        tipo="bloqueio"
                    ).delete()

        agendamento.delete()
        return redirect('listar_agendamentos', tenant_slug=request.tenant.slug)

    return render(request, 'clients/confirmar_exclusao.html', {
        'agendamento': agendamento
    })


@login_required
def escolher_servico(request, tenant_slug=None):
    servicos = Servico.objects.filter(tenant=request.tenant, ativo=True)
    erro = None

    cliente, _ = Cliente.objects.get_or_create(
    id_usuario=request.user,
    defaults={'tenant': request.tenant}
)
    if cliente.bloqueado:
        return render(request, 'clients/cliente_bloqueado.html')

    if request.method == "POST":
        servico_id = request.POST.get("servico")

        if not servico_id:
            erro = "Selecione um serviço para continuar."
        else:
            request.session["servico_id"] = servico_id
            return redirect("agendar", tenant_slug=request.tenant.slug)

    return render(request, "clients/servicos.html", {
        "servicos": servicos,
        "erro": erro,
    })

@login_required
def sobre(request, tenant_slug=None):
    from .models import HorarioFuncionamento

    DIAS = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]

    horarios_semana = []
    for dia_num, dia_nome in DIAS:
        horarios = HorarioFuncionamento.objects.filter(
            tenant=request.tenant,
            dia_semana=dia_num,
        ).order_by('horario').values_list('horario', flat=True)

        if horarios:
            abertura   = horarios[0].strftime('%H:%M')
            fechamento = horarios[len(horarios) - 1].strftime('%H:%M')
            horarios_semana.append({
                'dia': dia_nome,
                'abertura': abertura,
                'fechamento': fechamento,
                'fechado': False,
            })
        else:
            horarios_semana.append({
                'dia': dia_nome,
                'fechado': True,
            })

    return render(request, 'clients/sobre.html', {
        'horarios_semana': horarios_semana,
    })

@login_required
def perfil(request, tenant_slug=None):
    return render(request, 'clients/perfil.html')

@login_required
def suporte(request, tenant_slug=None):
    return render(request, 'clients/suporte.html')


def tutorial(request, tenant_slug=None):
    return render(request, 'clients/tutorial.html')


# ── UTILITÁRIOS INTERNOS ──────────────────────────────────────────────────────

def _horario_esta_bloqueado(tenant, data, horario):
    if isinstance(horario, str):
        horario = datetime.strptime(horario, '%H:%M').time()

    bloqueios = HorarioBloqueado.objects.filter(tenant=tenant, data=data)

    dia_bloqueado = bloqueios.filter(horario__isnull=True, tipo='bloqueio').exists()
    bloq_manual   = bloqueios.filter(horario=horario, tipo='bloqueio').exists()
    lib_manual    = bloqueios.filter(horario=horario, tipo='liberado').exists()

    return (dia_bloqueado and not lib_manual) or bloq_manual






def bloquear_slot(request):
    """Chamado via AJAX quando o cliente clica em um horário."""
    servico_id = request.POST.get('servico_id')
    data = request.POST.get('data')
    horario = request.POST.get('horario')
    pedido_id = request.POST.get('pedido_id')  # None na primeira vez

    servico = Servico.objects.get(id=servico_id, tenant=request.tenant)
    cliente, _ = Cliente.objects.get_or_create(
    id_usuario=request.user, defaults={'tenant': request.tenant}
)

    # Limpa lixo expirado antes de tentar (mantém banco saudável)
    PedidoReserva.objects.filter(
        status__in=['bloqueado', 'aguardando_pagamento'],
        expira_em__lt=timezone.now(),
    ).delete()  # CASCADE apaga os slots junto

    try:
        with transaction.atomic():
            if pedido_id:
                pedido = PedidoReserva.objects.get(id=pedido_id, cliente=cliente, status='bloqueado')
            else:
                pedido = PedidoReserva.objects.create(
                    tenant=request.tenant,
                    cliente=cliente,
                    status='bloqueado',
                    expira_em=timezone.now() + timedelta(minutes=10),
                )

            slot = SlotReservado.objects.create(
                pedido=pedido,
                tenant=request.tenant,
                servico=servico,
                data=data,
                horario=horario,
                preco=servico.preco,
            )

            pedido.valor_total += servico.preco
            pedido.save()

    except IntegrityError:
        # Alguém já travou esse horário no mesmo instante
        return JsonResponse({'ok': False, 'erro': 'Esse horário acabou de ser reservado por outra pessoa.'}, status=409)

    return JsonResponse({
        'ok': True,
        'pedido_id': pedido.id,
        'expira_em': pedido.expira_em.isoformat(),
        'valor_total': str(pedido.valor_total),
        'slot_id': slot.id,
    })


def desbloquear_slot(request):
    slot_id = request.POST.get('slot_id')
    cliente, _ = Cliente.objects.get_or_create(
        id_usuario=request.user, defaults={'tenant': request.tenant}
    )
    slot = SlotReservado.objects.get(id=slot_id, pedido__cliente=cliente)
    pedido = slot.pedido
    pedido.valor_total -= slot.preco
    slot.delete()

    if not pedido.slots.exists():
        pedido.delete()
    else:
        pedido.save()

    return JsonResponse({'ok': True})



logger = logging.getLogger('pagamentos')


@login_required
@rate_limit('bloquear_intervalo', limit=10, period_seconds=60)
def bloquear_intervalo(request, tenant_slug=None):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'erro': 'Método não permitido.'}, status=405)

    servico_id = request.POST.get('servico_id')
    data = request.POST.get('data')
    horario_inicio = request.POST.get('horario_inicio')
    horario_fim = request.POST.get('horario_fim')
    pedido_id = request.POST.get('pedido_id')

    if not all([servico_id, data, horario_inicio, horario_fim]):
        return JsonResponse({'ok': False, 'erro': 'Dados incompletos.'}, status=400)

    # Verifica que o serviço pertence ao tenant atual (IDOR protection)
    servico = get_object_or_404(Servico, id=servico_id, tenant=request.tenant, ativo=True)
    cliente, _ = Cliente.objects.get_or_create(
        id_usuario=request.user, defaults={'tenant': request.tenant}
    )

    # Verifica que o cliente pertence ao tenant atual
    if cliente.tenant != request.tenant:
        logger.warning(f'Tentativa de acesso cross-tenant | user={request.user.id}')
        return JsonResponse({'ok': False, 'erro': 'Acesso negado.'}, status=403)

    data_convertida = converter_data(data)
    if not data_convertida:
        return JsonResponse({'ok': False, 'erro': 'Data inválida.'}, status=400)

    PedidoReserva.objects.filter(
        status__in=['bloqueado', 'aguardando_pagamento'],
        expira_em__lt=timezone.now(),
    ).delete()

    try:
        inicio_dt = datetime.strptime(horario_inicio, '%H:%M')
        fim_dt = datetime.strptime(horario_fim, '%H:%M')
    except ValueError:
        return JsonResponse({'ok': False, 'erro': 'Horário inválido.'}, status=400)

    if fim_dt <= inicio_dt:
        fim_dt += timedelta(days=1)

    blocos = []
    atual = inicio_dt
    while atual < fim_dt:
        blocos.append(atual.strftime('%H:%M'))
        atual += timedelta(minutes=30)

    if not blocos:
        return JsonResponse({'ok': False, 'erro': 'Intervalo inválido.'}, status=400)

    # Tenta adquirir locks para todos os blocos antes de qualquer escrita
    locks_adquiridos = []
    for horario_str in blocos:
        if not adquirir_lock_slot(request.tenant.id, servico.id, data_convertida, horario_str):
            # Libera locks já adquiridos
            for h in locks_adquiridos:
                liberar_lock_slot(request.tenant.id, servico.id, data_convertida, h)
            return JsonResponse({'ok': False, 'erro': 'Um dos horários está sendo reservado agora. Tente novamente.'}, status=409)
        locks_adquiridos.append(horario_str)

    try:
        with transaction.atomic():
            if pedido_id:
                try:
                    pedido = PedidoReserva.objects.select_for_update().get(
                        id=pedido_id, cliente=cliente, tenant=request.tenant, status='bloqueado'
                    )
                    pedido.slots.all().delete()
                    pedido.valor_total = Decimal('0')
                except PedidoReserva.DoesNotExist:
                    pedido = PedidoReserva.objects.create(
                        tenant=request.tenant, cliente=cliente, status='bloqueado',
                        expira_em=timezone.now() + timedelta(minutes=10),
                    )
            else:
                pedido = PedidoReserva.objects.create(
                    tenant=request.tenant, cliente=cliente, status='bloqueado',
                    expira_em=timezone.now() + timedelta(minutes=10),
                )

            blocos_por_duracao = servico.duracao_minutos / 30
            preco_por_bloco = Decimal(str(servico.preco)) / Decimal(str(blocos_por_duracao))

            for horario_str in blocos:
                SlotReservado.objects.create(
                    pedido=pedido, tenant=request.tenant, servico=servico,
                    data=data_convertida, horario=horario_str, preco=preco_por_bloco,
                )
                pedido.valor_total += preco_por_bloco

            pedido.save()

    except IntegrityError:
        return JsonResponse({'ok': False, 'erro': 'Um dos horários acabou de ser reservado por outra pessoa.'}, status=409)
    finally:
        # Sempre libera os locks
        for h in locks_adquiridos:
            liberar_lock_slot(request.tenant.id, servico.id, data_convertida, h)

    logger.info(f'Intervalo bloqueado | pedido={pedido.id} | tenant={request.tenant.slug} | valor={pedido.valor_total}')

    return JsonResponse({
        'ok': True,
        'pedido_id': pedido.id,
        'expira_em': pedido.expira_em.isoformat(),
        'valor_total': str(pedido.valor_total),
    })


def disponibilidade_quadra(request, servico_id, data):
    PedidoReserva.objects.filter(
        status__in=['bloqueado', 'aguardando_pagamento'],
        expira_em__lt=timezone.now(),
    ).delete()

    cliente, _ = Cliente.objects.get_or_create(
        id_usuario=request.user, defaults={'tenant': request.tenant}
    )

    bloqueados = SlotReservado.objects.filter(
        servico_id=servico_id, data=data,
    ).exclude(pedido__cliente=cliente).values_list('horario', flat=True)

    meus_bloqueios = SlotReservado.objects.filter(
        servico_id=servico_id, data=data, pedido__cliente=cliente,
    ).values_list('horario', flat=True)

    confirmados = Agendamento.objects.filter(
        servico_id=servico_id, data=data, status__in=['pendente', 'presente'],
    ).values_list('horario', flat=True)

    return JsonResponse({
        'ocupados': [h.strftime('%H:%M') for h in list(bloqueados) + list(confirmados)],
        'meus_selecionados': [h.strftime('%H:%M') for h in meus_bloqueios],
    })



import mercadopago
from django.conf import settings

@login_required
def finalizar_pagamento(request, pedido_id, tenant_slug=None):
    cliente, _ = Cliente.objects.get_or_create(
        id_usuario=request.user, defaults={'tenant': request.tenant}
    )

    # Garante ownership + tenant (IDOR protection)
    pedido = get_object_or_404(
        PedidoReserva, id=pedido_id, cliente=cliente, tenant=request.tenant
    )

    # Recalcula o valor no backend — nunca confia no frontend
    valor_real = calcular_valor_pedido(pedido)

    if valor_real <= 0:
        logger.warning(f'Pedido sem valor | pedido={pedido.id} | user={request.user.id}')
        return JsonResponse({'erro': 'Pedido inválido. Faça uma nova reserva.'}, status=400)

    # Atualiza valor_total com o calculado no backend (proteção contra manipulação)
    if pedido.valor_total != valor_real:
        pedido.valor_total = valor_real
        pedido.save(update_fields=['valor_total'])

    if pedido.status == 'bloqueado':
        pedido.status = 'aguardando_pagamento'
        pedido.save(update_fields=['status'])

    pagamento = Pagamento.objects.filter(pedido=pedido).first()

    if pagamento and pagamento.status == 'aprovado':
        return render(request, 'clients/pagamento.html', {
            'pedido': pedido,
            'pagamento': pagamento,
            'tenant_slug': request.tenant.slug,
            'ja_aprovado': True,
        })

    if not pagamento:
        sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)

        payment_data = {
            "transaction_amount": float(valor_real),
            "description": f"Reserva {request.tenant.nome}",
            "payment_method_id": "pix",
            "payer": {
                "email": request.user.email or f"cliente_{request.user.id}@reserva.internal",
                "first_name": cliente.id_usuario.username.split('__')[0],
            },
            "metadata": {
                "pedido_id": pedido.id,
                "tenant_slug": request.tenant.slug,
            },
        }

        resultado = sdk.payment().create(payment_data)
        resposta = resultado.get("response", {})

        if "id" not in resposta:
            logger.error(f'MP erro ao criar pagamento | pedido={pedido.id} | erro={resposta.get("message")}')
            return JsonResponse({
                "erro": "Não foi possível gerar o pagamento. Tente novamente.",
            }, status=400)

        dados_pix = resposta.get("point_of_interaction", {}).get("transaction_data", {})

        pagamento = Pagamento.objects.create(
            pedido=pedido,
            mp_payment_id=str(resposta["id"]),
            valor=valor_real,
            qr_code=dados_pix.get("qr_code", ""),
            qr_code_base64=dados_pix.get("qr_code_base64", ""),
        )

        logger.info(f'Pagamento criado | pedido={pedido.id} | mp_id={resposta["id"]} | valor={valor_real}')

    return render(request, 'clients/pagamento.html', {
        'pedido': pedido,
        'pagamento': pagamento,
        'tenant_slug': request.tenant.slug,
    })


@login_required
def verificar_status_pagamento(request, tenant_slug=None, pedido_id=None):
    cliente, _ = Cliente.objects.get_or_create(
        id_usuario=request.user, defaults={'tenant': request.tenant}
    )

    # Garante ownership + tenant
    pedido = get_object_or_404(PedidoReserva, id=pedido_id, cliente=cliente, tenant=request.tenant)
    pagamento = get_object_or_404(Pagamento, pedido=pedido)

    if pagamento.status == 'aprovado':
        return JsonResponse({'status': 'aprovado'})

    if pedido.esta_expirado():
        pagamento.status = 'expirado'
        pagamento.save()
        pedido.status = 'expirado'
        pedido.save()
        return JsonResponse({'status': 'expirado'})

    # Consulta o status real no MP — nunca confia apenas no banco
    sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)
    resultado = sdk.payment().get(pagamento.mp_payment_id)
    resposta = resultado.get("response", {})
    status_mp = resposta.get("status")

    if status_mp == "approved":
        # Valida o valor aprovado contra o calculado no backend
        valor_mp = resposta.get("transaction_amount", 0)
        if not validar_valor_pagamento(pedido, valor_mp):
            logger.error(
                f'Valor divergente | pedido={pedido.id} '
                f'| esperado={calcular_valor_pedido(pedido)} | recebido={valor_mp}'
            )
            return JsonResponse({'status': 'pendente'})

        # Idempotência: não processa duas vezes
        if pagamento_ja_processado(pagamento.mp_payment_id):
            return JsonResponse({'status': 'aprovado'})

        with transaction.atomic():
            pagamento.status = 'aprovado'
            pagamento.save()
            pedido.status = 'confirmado'
            pedido.save()

            slots_ordenados = pedido.slots.select_related('servico').order_by('servico', 'horario')
            from itertools import groupby
            for servico_id, slots_grupo in groupby(slots_ordenados, key=lambda s: s.servico_id):
                slots_lista = list(slots_grupo)
                slot_inicio = slots_lista[0]
                slot_fim = slots_lista[-1]
                horario_fim_dt = datetime.combine(slot_fim.data, slot_fim.horario) + timedelta(minutes=30)

                Agendamento.objects.create(
                    tenant=slot_inicio.tenant,
                    cliente=pedido.cliente,
                    servico=slot_inicio.servico,
                    data=slot_inicio.data,
                    horario=slot_inicio.horario,
                    horario_fim=horario_fim_dt.time(),
                    status='pendente',
                    origem='cliente',
                )

            pedido.slots.all().delete()
            marcar_pagamento_processado(pagamento.mp_payment_id)

        logger.info(f'Pagamento aprovado | pedido={pedido.id} | mp_id={pagamento.mp_payment_id}')
        return JsonResponse({'status': 'aprovado'})

    if status_mp in ('rejected', 'cancelled'):
        pagamento.status = 'cancelado'
        pagamento.save()
        logger.info(f'Pagamento recusado | pedido={pedido.id} | status_mp={status_mp}')
        return JsonResponse({'status': 'recusado'})

    return JsonResponse({'status': 'pendente'})


@csrf_exempt
@require_POST
def webhook_mercadopago(request):
    """
    Webhook seguro: valida assinatura, idempotência e valor antes de confirmar.
    """
    if not validar_webhook_mercadopago(request):
        return JsonResponse({'erro': 'Assinatura inválida.'}, status=401)

    try:
        dados = _json.loads(request.body)
    except _json.JSONDecodeError:
        return JsonResponse({'erro': 'JSON inválido.'}, status=400)

    if dados.get('type') != 'payment':
        return JsonResponse({'ok': True})

    payment_id = str(dados.get('data', {}).get('id', ''))
    if not payment_id:
        return JsonResponse({'erro': 'payment_id ausente.'}, status=400)

    # Idempotência — webhook duplicado não faz nada
    if pagamento_ja_processado(payment_id):
        logger.info(f'Webhook duplicado ignorado | mp_id={payment_id}')
        return JsonResponse({'ok': True})

    try:
        pagamento = Pagamento.objects.select_related('pedido__tenant', 'pedido__cliente').get(
            mp_payment_id=payment_id
        )
    except Pagamento.DoesNotExist:
        logger.warning(f'Webhook: pagamento não encontrado | mp_id={payment_id}')
        return JsonResponse({'ok': True})

    if pagamento.status == 'aprovado':
        return JsonResponse({'ok': True})

    # Consulta o MP para confirmar (nunca confia só no webhook)
    sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)
    resultado = sdk.payment().get(payment_id)
    resposta = resultado.get("response", {})
    status_mp = resposta.get("status")

    if status_mp != "approved":
        return JsonResponse({'ok': True})

    # Valida valor
    valor_mp = resposta.get("transaction_amount", 0)
    pedido = pagamento.pedido
    if not validar_valor_pagamento(pedido, valor_mp):
        logger.error(f'Webhook: valor divergente | mp_id={payment_id} | valor_mp={valor_mp}')
        return JsonResponse({'ok': True})

    with transaction.atomic():
        pagamento.status = 'aprovado'
        pagamento.save()
        pedido.status = 'confirmado'
        pedido.save()

        slots_ordenados = pedido.slots.select_related('servico').order_by('servico', 'horario')
        from itertools import groupby
        for servico_id, slots_grupo in groupby(slots_ordenados, key=lambda s: s.servico_id):
            slots_lista = list(slots_grupo)
            slot_inicio = slots_lista[0]
            slot_fim = slots_lista[-1]
            horario_fim_dt = datetime.combine(slot_fim.data, slot_fim.horario) + timedelta(minutes=30)

            Agendamento.objects.get_or_create(
                tenant=slot_inicio.tenant,
                cliente=pedido.cliente,
                servico=slot_inicio.servico,
                data=slot_inicio.data,
                horario=slot_inicio.horario,
                defaults={
                    'horario_fim': horario_fim_dt.time(),
                    'status': 'pendente',
                    'origem': 'cliente',
                }
            )

        pedido.slots.all().delete()
        marcar_pagamento_processado(payment_id)

    logger.info(f'Webhook processado | mp_id={payment_id} | pedido={pedido.id}')
    return JsonResponse({'ok': True})