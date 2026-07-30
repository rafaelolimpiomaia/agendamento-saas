from django.contrib import admin
from .models import SuperAdminUser, StatusSalao, LogAdministrativo

@admin.register(SuperAdminUser)
class SuperAdminUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'nome', 'ativo', 'ultimo_login')

@admin.register(StatusSalao)
class StatusSalaoAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'status', 'pagamento_em_dia', 'vencimento')
    list_filter = ('status', 'pagamento_em_dia')

@admin.register(LogAdministrativo)
class LogAdministrativoAdmin(admin.ModelAdmin):
    list_display = ('acao', 'tenant', 'super_admin', 'criado_em')
    list_filter = ('acao',)