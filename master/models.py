from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone


class SuperAdminUser(models.Model):
    """
    Usuário do Painel Master. Completamente separado do User do Django
    usado pelos salões e clientes — sem relação nenhuma com Tenant.
    """
    username    = models.CharField(max_length=50, unique=True)
    senha_hash  = models.CharField(max_length=255)
    nome        = models.CharField(max_length=100)
    ativo       = models.BooleanField(default=True)
    criado_em   = models.DateTimeField(auto_now_add=True)
    ultimo_login = models.DateTimeField(null=True, blank=True)

    def set_senha(self, senha_plana):
        self.senha_hash = make_password(senha_plana)

    def checar_senha(self, senha_plana):
        return check_password(senha_plana, self.senha_hash)

    def __str__(self):
        return self.username

    class Meta:
        verbose_name = 'Super Admin'
        verbose_name_plural = 'Super Admins'

# master/models.py (continuação)

class StatusSalao(models.Model):
    """
    Estende o Tenant com informações administrativas da plataforma.
    Relação 1-para-1 — não mexe no model Tenant existente.
    """

    STATUS_CHOICES = [
        ('ativo',      'Ativo'),
        ('teste',      'Em teste'),
        ('congelado',  'Congelado'),
        ('suspenso',   'Suspenso'),
        ('cancelado',  'Cancelado'),
    ]

    tenant = models.OneToOneField(
        'agendamento.Tenant',
        on_delete=models.CASCADE,
        related_name='status_admin',
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='teste')

    pagamento_em_dia   = models.BooleanField(default=True)
    ultimo_pagamento   = models.DateField(null=True, blank=True)
    vencimento         = models.DateField(null=True, blank=True)

    observacoes_internas = models.TextField(blank=True, default='')

    congelado_em    = models.DateTimeField(null=True, blank=True)
    congelado_motivo = models.CharField(max_length=200, blank=True, default='')

    ultimo_acesso   = models.DateTimeField(null=True, blank=True)

    atualizado_em = models.DateTimeField(auto_now=True)

    @property
    def dias_para_vencimento(self):
        if not self.vencimento:
            return None
        from datetime import date
        return (self.vencimento - date.today()).days

    @property
    def esta_congelado(self):
        return self.status == 'congelado'

    @property
    def esta_suspenso(self):
        return self.status == 'suspenso'

    def __str__(self):
        return f'{self.tenant.nome} — {self.get_status_display()}'

    class Meta:
        verbose_name = 'Status do Salão'
        verbose_name_plural = 'Status dos Salões'

# master/models.py (continuação)

class LogAdministrativo(models.Model):
    """
    Registra toda ação executada pelo Super Admin sobre um salão.
    Base para auditoria futura.
    """
    ACAO_CHOICES = [
        ('congelar',    'Congelou a conta'),
        ('reativar',    'Reativou a conta'),
        ('suspender',   'Suspendeu a conta'),
        ('excluir',     'Excluiu o salão'),
        ('editar',      'Editou informações'),
        ('codigo',      'Gerou código de ativação'),
        ('login',       'Login no Painel Master'),
    ]

    super_admin = models.ForeignKey(SuperAdminUser, on_delete=models.SET_NULL, null=True)
    tenant      = models.ForeignKey('agendamento.Tenant', on_delete=models.SET_NULL, null=True, blank=True)
    acao        = models.CharField(max_length=20, choices=ACAO_CHOICES)
    detalhes    = models.TextField(blank=True, default='')
    criado_em   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        alvo = self.tenant.nome if self.tenant else '—'
        return f'{self.get_acao_display()} — {alvo} ({self.criado_em:%d/%m/%Y %H:%M})'

    class Meta:
        verbose_name = 'Log Administrativo'
        verbose_name_plural = 'Logs Administrativos'
        ordering = ['-criado_em']