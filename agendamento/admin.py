from django.contrib import admin
from .models import Cliente, Agendamento, Servico, CodigoConvite

@admin.register(CodigoConvite)
class CodigoConviteAdmin(admin.ModelAdmin):
    list_display  = ('codigo', 'usado', 'usado_por', 'criado_em')
    list_filter   = ('usado',)
    readonly_fields = ('criado_em', 'usado_por')
    actions = ['gerar_codigos']

    @admin.action(description='Gerar 5 novos códigos')
    def gerar_codigos(self, request, queryset):
        for _ in range(5):
            CodigoConvite.gerar()
        self.message_user(request, '5 novos códigos gerados com sucesso.')

class AgendamentoAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'data', 'horario')

admin.site.register(Cliente)
admin.site.register(Agendamento, AgendamentoAdmin)
admin.site.register(Servico)

# Register your models here.
