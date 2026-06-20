from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .models import Cliente, Agendamento, Servico, NotificacaoExclusao
from .forms import AgendamentoForm, IdentificarUsuarioForm , RedefinirSenhaForm, AgendamentoManualForm
from datetime import datetime, timedelta, date
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.contrib.admin.views.decorators import staff_member_required
from collections import defaultdict
import json, re
from .models import HorarioBloqueado
from django.utils import timezone
from .utils import (
    gerar_horarios,
    requer_horario_duplo,
    get_proximo_horario,
    is_excecao_almoco,
    is_horario_dentro_24h,
)
from django.contrib import messages
from decimal import Decimal
import calendar
from django.http import JsonResponse

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

            horarios_do_dia = gerar_horarios(ag.data)
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
        horarios_do_dia = gerar_horarios(dia_cursor)
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
                horarios_do_dia = gerar_horarios(agendamento.data)
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

    horarios = gerar_horarios(data_formatada)

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

    horarios_do_dia = gerar_horarios(data_convertida)

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
        username = request.POST.get("username")
        telefone = request.POST.get("telefone")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            return render(request, 'clients/register.html', {'erro': 'As senhas não coincidem!'})

        if User.objects.filter(username=username).exists():
            return render(request, 'clients/register.html', {'erro': 'Usuário já existe!'})

        user = User.objects.create_user(username=username, password=password)

        cliente, _ = Cliente.objects.get_or_create(
            id_usuario=user,
            defaults={'tenant': request.tenant}
        )
        cliente.telefone = telefone
        cliente.save()
        print("TENANT SLUG:", tenant_slug)
        print("REQUEST TENANT:", request.tenant)

        return redirect('login', tenant_slug=request.tenant.slug)

    return render(request, 'clients/register.html')


def login_view(request, tenant_slug=None):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user:
            login(request, user)

            if user.is_staff:
                return redirect('painel_admin', tenant_slug=request.tenant.slug)
            else:
                return redirect('home', tenant_slug=request.tenant.slug)

        return render(request, 'clients/login.html', {'erro': 'Login inválido! Verifique os dados da conta ou Crie uma!'})

    return render(request, 'clients/login.html')


def logout_view(request, tenant_slug=None):
    slug = request.tenant.slug
    logout(request)
    return redirect('login', tenant_slug=slug)


def esqueci_senha(request, tenant_slug=None):
    form = IdentificarUsuarioForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        nome = form.cleaned_data["nome"]
        telefone = form.cleaned_data["telefone"]

        usuario = User.objects.filter(username__iexact=nome).first()

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

        request.session["redefinir_nome"] = usuario.username
        return redirect("redefinir_senha", tenant_slug=request.tenant.slug)

    return render(request, "clients/esqueci_senha.html", {"form": form})


def redefinir_senha(request, tenant_slug=None):
    nome = request.session.get("redefinir_nome")

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
            messages.success(request, "Senha redefinida com sucesso! Pressione o botão 'Voltar para o login' e entre com sua nova senha!")
        else:
            messages.error(request, "Usuário não encontrado.")
            return redirect("esqueci_senha", tenant_slug=request.tenant.slug)

    return render(request, "clients/redefinir_senha.html", {"form": form, "nome": nome})


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

    duplo = requer_horario_duplo(servico)

    data_selecionada = request.GET.get("data") or request.POST.get("data")
    data_convertida = converter_data(data_selecionada)

    horarios = gerar_horarios(data_convertida)
    horarios_ocupados = []

    if data_convertida:
        agendamentos_do_dia = Agendamento.objects.filter(
            tenant=request.tenant,
            data=data_convertida)
        horarios_ocupados = [
            ag.horario.strftime("%H:%M") for ag in agendamentos_do_dia
        ]

    bloqueios = (
        HorarioBloqueado.objects.filter(
            tenant=request.tenant,
            data=data_convertida)
        if data_convertida
        else HorarioBloqueado.objects.none()
    )

    dia_bloqueado = bloqueios.filter(
        horario__isnull=True,
        tipo='bloqueio'
    ).exists()

    if request.method == "POST":
        form = AgendamentoForm(request.POST)
        horario_selecionado = request.POST.get("horario")

        ja_existe = False
        if data_convertida and horario_selecionado:
            ja_existe = Agendamento.objects.filter(
                tenant=request.tenant,
                data=data_convertida,
                horario=horario_selecionado
            ).exists()

        bloqueado = False

        if data_convertida and horario_selecionado:
            horario_time = datetime.strptime(horario_selecionado, "%H:%M").time()

            horario_bloqueado = bloqueios.filter(
                horario=horario_time,
                tipo='bloqueio'
            ).exists()

            horario_liberado = bloqueios.filter(
                horario=horario_time,
                tipo='liberado'
            ).exists()

            if (dia_bloqueado and not horario_liberado) or horario_bloqueado:
                bloqueado = True

        erro_duplo = None
        if duplo and horario_selecionado and data_convertida and not bloqueado and not ja_existe:
            if not is_excecao_almoco(horario_selecionado):
                proximo = get_proximo_horario(horario_selecionado, horarios)

                if proximo is not None:
                    proximo_ocupado_ag = Agendamento.objects.filter(
                        tenant=request.tenant,
                        data=data_convertida,
                        horario=datetime.strptime(proximo, "%H:%M").time()
                    ).exists()

                    proximo_time = datetime.strptime(proximo, "%H:%M").time()
                    proximo_bloqueado_manual = bloqueios.filter(
                        horario=proximo_time,
                        tipo='bloqueio'
                    ).exists()
                    proximo_liberado_manual = bloqueios.filter(
                        horario=proximo_time,
                        tipo='liberado'
                    ).exists()
                    proximo_bloqueado = (
                        proximo_ocupado_ag
                        or ((dia_bloqueado and not proximo_liberado_manual) or proximo_bloqueado_manual)
                    )

                    if proximo_bloqueado:
                        erro_duplo = (
                            f"Este serviço ocupa dois horários consecutivos "
                            f"({horario_selecionado} e {proximo}), "
                            f"mas {proximo} já está ocupado. Escolha outro horário."
                        )

        if bloqueado:
            form.add_error("horario", "Este horário está bloqueado.")
        elif ja_existe:
            form.add_error("horario", "Esse horário já está ocupado para essa data.")
        elif erro_duplo:
            form.add_error("horario", erro_duplo)
        elif data_convertida and horario_selecionado and is_horario_dentro_24h(data_convertida, horario_selecionado):
            limite = timezone.localtime() + timedelta(hours=24)
            form.add_error(
                "horario",
                f"Agendamentos devem ser feitos com pelo menos 24 horas de antecedência. "
                f"O horário mais cedo disponível é {limite.strftime('%d/%m/%Y às %H:%M')}."
            )
        elif form.is_valid():
            agendamento = form.save(commit=False)
            agendamento.tenant = request.tenant
            agendamento.cliente = cliente
            agendamento.servico = servico

            try:
                agendamento.full_clean()
                agendamento.save()

                if duplo and not is_excecao_almoco(horario_selecionado):
                    proximo = get_proximo_horario(horario_selecionado, horarios)
                    if proximo is not None:
                        proximo_time = datetime.strptime(proximo, "%H:%M").time()
                        HorarioBloqueado.objects.update_or_create(
                            tenant=request.tenant,
                            data=data_convertida,
                            horario=proximo_time,
                            defaults={"tipo": "bloqueio"}
                        )

                request.session.pop("servico_id", None)
                return redirect('listar_agendamentos', tenant_slug=request.tenant.slug)

            except ValidationError as e:
                for field, errors in e.message_dict.items():
                    for error in errors:
                        form.add_error(field, error)

            except IntegrityError:
                form.add_error("horario", "Esse horário acabou de ser ocupado. Tente outro.")
    else:
        form = AgendamentoForm(initial={"data": data_selecionada})

    bloqueados = []
    horarios_menos_24h = []

    for h in horarios:
        horario_time = datetime.strptime(h, "%H:%M").time()

        if data_convertida and is_horario_dentro_24h(data_convertida, h):
            horarios_menos_24h.append(h)
            continue

        horario_bloqueado_manual = bloqueios.filter(
            horario=horario_time,
            tipo='bloqueio'
        ).exists()

        horario_liberado_manual = bloqueios.filter(
            horario=horario_time,
            tipo='liberado'
        ).exists()

        if (dia_bloqueado and not horario_liberado_manual) or horario_bloqueado_manual:
            bloqueados.append(h)
        elif duplo and not is_excecao_almoco(h):
            proximo = get_proximo_horario(h, horarios)

            if proximo is not None:
                proximo_time = datetime.strptime(proximo, "%H:%M").time()

                proximo_bloq_manual = bloqueios.filter(
                    horario=proximo_time,
                    tipo='bloqueio'
                ).exists()
                proximo_lib_manual = bloqueios.filter(
                    horario=proximo_time,
                    tipo='liberado'
                ).exists()
                proximo_ocupado_ag = proximo in horarios_ocupados
                proximo_indisponivel = (
                    proximo_ocupado_ag
                    or ((dia_bloqueado and not proximo_lib_manual) or proximo_bloq_manual)
                )

                if proximo_indisponivel:
                    bloqueados.append(h)

    return render(request, 'clients/agendar.html', {
        'form': form,
        'horarios': horarios,
        'horarios_ocupados': horarios_ocupados,
        'data_selecionada': data_selecionada,
        'servico': servico,
        'bloqueados': bloqueados,
        'duplo': duplo,
        'horarios_menos_24h': horarios_menos_24h,
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
                horarios_do_dia = gerar_horarios(agendamento.data)
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
def perfil(request, tenant_slug=None):
    return render(request, 'clients/perfil.html')


@login_required
def sobre(request, tenant_slug=None):
    return render(request, 'clients/sobre.html')


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

# ─────────────────────────────────────────────────────────────────────────────