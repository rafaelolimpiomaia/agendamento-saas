from datetime import datetime, time, timedelta
from django.utils import timezone


def _gerar_todos_horarios():
    """Gera lista de todos os horários de 00:00 a 23:30 de 30 em 30 min."""
    horarios = []
    t = datetime.strptime("00:00", "%H:%M")
    while True:
        horarios.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
        if t.hour == 0 and t.minute == 0:
            break
    return horarios


TODOS_HORARIOS = _gerar_todos_horarios()  # ["00:00", "00:30", ..., "23:30"]


def gerar_horarios(data, tenant=None):
    """
    Retorna a lista de horários disponíveis para uma data.

    Prioridade:
    1. Se o tenant tem HorarioFuncionamento configurado → usa do banco
    2. Se não tem configuração → retorna [] (sem horários)

    Também verifica PeriodoBloqueio — se a data cair num período
    de bloqueio, retorna [] (dia fechado).
    """
    if not data:
        return []

    if isinstance(data, str):
        data = datetime.strptime(data, "%Y-%m-%d").date()

    if tenant is None:
        return []

    # Verifica se a data está em algum período de bloqueio
    from agendamento.models import PeriodoBloqueio
    bloqueado = PeriodoBloqueio.objects.filter(
        tenant=tenant,
        data_inicio__lte=data,
        data_fim__gte=data,
    ).exists()

    if bloqueado:
        return []

    # Busca horários configurados para o dia da semana
    from agendamento.models import HorarioFuncionamento
    horarios_qs = HorarioFuncionamento.objects.filter(
        tenant=tenant,
        dia_semana=data.weekday(),
    ).values_list('horario', flat=True)

    return [h.strftime("%H:%M") for h in horarios_qs]


# ── Horário de exceção do almoço ─────────────────────────────────────────────
HORARIO_EXCECAO_ALMOCO = time(9, 30)


def requer_horario_duplo(servico):
    if servico is None:
        return False
    return bool(getattr(servico, 'horario_duplo', False))


def get_proximo_horario(horario_str, lista_horarios):
    try:
        idx = lista_horarios.index(horario_str)
    except ValueError:
        return None
    if idx + 1 < len(lista_horarios):
        return lista_horarios[idx + 1]
    return None


def is_excecao_almoco(horario_str):
    try:
        h = datetime.strptime(horario_str, "%H:%M").time()
        return h == HORARIO_EXCECAO_ALMOCO
    except (ValueError, TypeError):
        return False


def is_horario_dentro_24h(data, horario_str):
    try:
        from zoneinfo import ZoneInfo
        horario_time = datetime.strptime(horario_str, "%H:%M").time()
        agendamento_naive = datetime.combine(data, horario_time)
        agendamento_dt = agendamento_naive.replace(tzinfo=ZoneInfo('America/Sao_Paulo'))
        agora = timezone.localtime()
        diferenca = agendamento_dt - agora
        return diferenca.total_seconds() < 86400
    except (ValueError, TypeError):
        return True