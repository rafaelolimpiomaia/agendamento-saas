from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import time
from django.utils.text import slugify

class Tenant(models.Model):
    nome        = models.CharField(max_length=50)
    slug        = models.SlugField(max_length=60, unique=True)
    telefone    = models.CharField(max_length=20)
    cnpj        = models.CharField(max_length=18, blank=True, default='')
    email       = models.EmailField()
    ativo       = models.BooleanField(default=True)
    criado_em   = models.DateTimeField(auto_now_add=True)
    # admin do salão (owner)
    admin       = models.OneToOneField(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='tenant_admin',
        null=True, blank=True,
    )

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nome)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Salão'
        verbose_name_plural = 'Salões'


class Cliente(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='clientes'
    )  # <-- NOVO
    id_usuario = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    telefone   = models.CharField(max_length=20)
    endereco   = models.CharField(max_length=60)
    bloqueado  = models.BooleanField(default=False)



class Agendamento(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='agendamentos'
    )  # <-- NOVO

    ORIGEM_ONLINE = 'online'
    ORIGEM_MANUAL = 'manual'
    ORIGEM_CHOICES = [
        (ORIGEM_ONLINE, 'Online'),
        (ORIGEM_MANUAL, 'Manual'),
    ]

    # cliente pode ser null para agendamentos manuais
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    servico = models.ForeignKey('Servico', on_delete=models.CASCADE, null=True, blank=True)
    data = models.DateField()
    horario = models.TimeField()
    descricao = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=10,
        choices=[
            ('pendente', 'Pendente'),
            ('presente', 'Presente'),
            ('ausente', 'Ausente'),
        ],
        default='pendente',
    )

    # ── Campos de agendamento manual ─────────────────────────────────────
    origem = models.CharField(
        max_length=10,
        choices=ORIGEM_CHOICES,
        default=ORIGEM_ONLINE,
        verbose_name='Origem',
    )
    nome_manual = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Nome (agendamento manual)',
    )
    telefone_manual = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='Telefone (agendamento manual)',
    )
    # ─────────────────────────────────────────────────────────────────────

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'data', 'horario'],  # tenant entra na constraint
                name='unique_agendamento_tenant_data_horario'
            )
        ]

    # ── Propriedades de conveniência ──────────────────────────────────────
    @property
    def is_manual(self):
        return self.origem == self.ORIGEM_MANUAL

    @property
    def nome_cliente(self):
        """Retorna o nome independente da origem do agendamento."""
        if self.is_manual:
            return self.nome_manual or '—'
        if self.cliente:
            return self.cliente.id_usuario.get_full_name() or self.cliente.id_usuario.username
        return '—'

    @property
    def telefone_cliente(self):
        """Retorna o telefone independente da origem do agendamento."""
        if self.is_manual:
            return self.telefone_manual or '—'
        if self.cliente:
            return self.cliente.telefone
        return '—'
    # ─────────────────────────────────────────────────────────────────────

    def clean(self):
        errors = {}

        now = timezone.localtime()

        if self.data and self.data < now.date():
            errors['data'] = 'Não é permitido agendar em datas passadas.'

        if self.horario:
            if self.horario < time(8, 0) or self.horario > time(22, 0):
                errors['horario'] = 'Horário permitido apenas entre 08:00 e 22:00.'

        if self.data == now.date() and self.horario:
            if self.horario <= now.time():
                errors['horario'] = 'Não é possível agendar horários anteriores ao horário atual.'

        # ── Regra de antecedência mínima de 24 horas ──
        # Agendamentos manuais feitos pelo admin dispensam a regra de 24h.
        if self.origem != self.ORIGEM_MANUAL:
            if 'data' not in errors and 'horario' not in errors:
                if self.data and self.horario:
                    from datetime import datetime as dt
                    from zoneinfo import ZoneInfo

                    tz = ZoneInfo('America/Sao_Paulo')
                    agendamento_naive = dt.combine(self.data, self.horario)
                    agendamento_dt = agendamento_naive.replace(tzinfo=tz)
                    agora = timezone.localtime()
                    diferenca = agendamento_dt - agora

                    if diferenca.total_seconds() < 86400:
                        errors['horario'] = (
                            'Agendamentos devem ser feitos com pelo menos 24 horas de antecedência. '
                            'Escolha uma data e horário a partir de '
                            f'{(agora + __import__("datetime").timedelta(hours=24)).strftime("%d/%m/%Y às %H:%M")}.'
                        )
        # ─────────────────────────────────────────────────────────────────

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        nome = self.nome_cliente
        return f"{nome} - {self.data} {self.horario}"


class Servico(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='servicos'
    )  # <-- NOVO
    nome          = models.CharField(max_length=100)
    descricao     = models.CharField(max_length=200, blank=True)
    ativo         = models.BooleanField(default=True)
    preco         = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    duracao_minutos = models.PositiveIntegerField(default=60)
    horario_duplo = models.BooleanField(default=False)


class NotificacaoExclusao(models.Model):
    """
    Armazena o aviso de exclusão de agendamento pelo ADM.
    Exibido como pop-up uma única vez ao cliente na próxima vez que entrar.
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='notificacoes_exclusao')
    servico_nome = models.CharField(max_length=100)
    data_agendamento = models.DateField()
    horario_agendamento = models.TimeField()
    criado_em = models.DateTimeField(auto_now_add=True)
    visualizado = models.BooleanField(default=False)

    def __str__(self):
        return f"Notif. exclusão p/ {self.cliente} — {self.data_agendamento} {self.horario_agendamento}"


class HorarioBloqueado(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='horarios_bloqueados'
    )  # <-- NOVO
    data    = models.DateField()
    horario = models.TimeField(null=True, blank=True)
    tipo    = models.CharField(max_length=10, choices=[
        ('bloqueio', 'Bloqueio'), ('liberado', 'Liberado')
    ])

    class Meta:
        unique_together = ['tenant', 'data', 'horario']  # tenant na unique
