from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import time
from django.utils.text import slugify
import secrets

class Tenant(models.Model):
    TIPO_CHOICES = [
        ('salao',      'Salão de Beleza'),
        ('barbearia',  'Barbearia'),
        ('studio',     'Studio de Unhas'),
        ('outro',      'Outro'),
    ]

    # ── Estabelecimento ───────────────────────────────────────
    nome             = models.CharField(max_length=100)
    slug             = models.SlugField(max_length=60, unique=True)
    tipo_negocio     = models.CharField(max_length=20, choices=TIPO_CHOICES, default='salao')

    # ── Dono ─────────────────────────────────────────────────
    nome_responsavel = models.CharField(max_length=100, default='')
    telefone         = models.CharField(max_length=20)
    email            = models.EmailField()

    # ── Termos ───────────────────────────────────────────────
    termos_aceitos    = models.BooleanField(default=False)
    termos_aceitos_em = models.DateTimeField(null=True, blank=True)

    # ── Controle ─────────────────────────────────────────────
    ativo     = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    admin     = models.OneToOneField(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='tenant_admin',
        null=True, blank=True,
    )

    excluido_em = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nome)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Salão'
        verbose_name_plural = 'Salões'

class CodigoConvite(models.Model):
    codigo    = models.CharField(max_length=20, unique=True)
    usado     = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    usado_por = models.OneToOneField(
        'Tenant',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='codigo_convite',
    )

    def __str__(self):
        status = f"usado por {self.usado_por.nome}" if self.usado else "disponível"
        return f"{self.codigo} — {status}"

    @classmethod
    def gerar(cls):
        """Gera e salva um novo código aleatório."""
        codigo = secrets.token_urlsafe(8)
        return cls.objects.create(codigo=codigo)

    class Meta:
        verbose_name = 'Código de Convite'
        verbose_name_plural = 'Códigos de Convite'


class ConfiguracaoSalao(models.Model):
    PUBLICO_CHOICES = [
        ('homens',   'Homens'),
        ('mulheres', 'Mulheres'),
        ('ambos',    'Homens e Mulheres'),
    ]

    TIPO_CHOICES = [
        ('salao',      'Salão de Beleza'),
        ('barbearia',  'Barbearia'),
        ('studio',     'Studio de Unhas'),
        ('esmalteria', 'Esmalteria'),
        ('outro',      'Outro'),
    ]

    tenant       = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='configuracao')
    nome_exibicao = models.CharField(max_length=100, blank=True, default='')
    tipo_negocio  = models.CharField(max_length=20, choices=TIPO_CHOICES, blank=True, default='')
    telefone      = models.CharField(max_length=20, blank=True, default='')
    publico       = models.CharField(max_length=20, choices=PUBLICO_CHOICES, default='ambos', blank=True)
    endereco      = models.CharField(max_length=200, blank=True, default='')
    instagram     = models.CharField(max_length=60, blank=True, default='')
    cor_primaria  = models.CharField(max_length=7, blank=True, default='#0d6efd')

    def __str__(self):
        return f'Configuração — {self.tenant.nome}'

    class Meta:
        verbose_name = 'Configuração do Salão'
        verbose_name_plural = 'Configurações dos Salões'

class HorarioFuncionamento(models.Model):
    """
    Armazena os horários disponíveis por dia da semana para cada tenant.
    Cada registro representa UM horário disponível num dia específico.
    """
    DIA_CHOICES = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]

    tenant    = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='horarios_funcionamento')
    dia_semana = models.IntegerField(choices=DIA_CHOICES)
    horario   = models.TimeField()

    class Meta:
        unique_together = ['tenant', 'dia_semana', 'horario']
        ordering = ['dia_semana', 'horario']
        verbose_name = 'Horário de Funcionamento'
        verbose_name_plural = 'Horários de Funcionamento'

    def __str__(self):
        return f'{self.get_dia_semana_display()} {self.horario.strftime("%H:%M")} — {self.tenant.nome}'


class PeriodoBloqueio(models.Model):
    """
    Períodos de bloqueio completo do salão (férias, feriados, etc).
    Funciona em conjunto com HorarioBloqueado já existente.
    """
    tenant      = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='periodos_bloqueio')
    data_inicio = models.DateField()
    data_fim    = models.DateField()
    motivo      = models.CharField(max_length=200, blank=True, default='')
    criado_em   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_inicio']
        verbose_name = 'Período de Bloqueio'
        verbose_name_plural = 'Períodos de Bloqueio'

    def __str__(self):
        return f'{self.tenant.nome} — {self.data_inicio} a {self.data_fim}'


class Cliente(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='clientes', null=True
    )  # <-- NOVO
    id_usuario = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    telefone   = models.CharField(max_length=20)
    endereco   = models.CharField(max_length=60)
    bloqueado  = models.BooleanField(default=False)

    @property
    def nome_exibicao(self):
        """Retorna o nome do cliente sem o sufixo __slug do tenant."""
        username = self.id_usuario.username
        return username.split('__')[0] if '__' in username else username

    def __str__(self):
        return self.nome_exibicao



class Agendamento(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='agendamentos', null=True
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
            return self.cliente.nome_exibicao
        return self.nome_manual or "—"

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
        Tenant, on_delete=models.CASCADE, related_name='servicos', null=True
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
        Tenant, on_delete=models.CASCADE, related_name='horarios_bloqueados', null=True
    )  # <-- NOVO
    data    = models.DateField()
    horario = models.TimeField(null=True, blank=True)
    tipo    = models.CharField(max_length=10, choices=[
        ('bloqueio', 'Bloqueio'), ('liberado', 'Liberado')
    ])

    class Meta:
        unique_together = ['tenant', 'data', 'horario']  # tenant na unique


class PedidoReserva(models.Model):
    STATUS_CHOICES = [
        ('bloqueado', 'Bloqueado (aguardando escolha de pagamento)'),
        ('aguardando_pagamento', 'Aguardando Pagamento'),
        ('confirmado', 'Confirmado'),
        ('expirado', 'Expirado'),
        ('cancelado', 'Cancelado'),
    ]

    tenant    = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    cliente   = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    status    = models.CharField(max_length=20, choices=STATUS_CHOICES, default='bloqueado')
    valor_total = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    expira_em = models.DateTimeField()  # criado_em + 10min

    def esta_expirado(self):
        return timezone.now() > self.expira_em


class SlotReservado(models.Model):
    """Cada linha = um bloco de 30min de UMA quadra. Um pedido pode ter várias."""
    pedido  = models.ForeignKey(PedidoReserva, on_delete=models.CASCADE, related_name='slots')
    tenant  = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    servico = models.ForeignKey('Servico', on_delete=models.CASCADE)  # a quadra
    data    = models.DateField()
    horario = models.TimeField()
    preco   = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'servico', 'data', 'horario'],
                name='unique_slot_tenant_servico_data_horario'
            )
        ]
