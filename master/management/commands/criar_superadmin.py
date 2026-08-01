from django.core.management.base import BaseCommand
from master.models import SuperAdminUser
 
 
class Command(BaseCommand):
    help = 'Cria o Super Admin do Painel Master se ainda não existir'
 
    def handle(self, *args, **options):
        username = 'erick'
        senha    = 'Trinda2020.'
 
        if SuperAdminUser.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(
                f'Super Admin "{username}" já existe. Nenhuma ação realizada.'
            ))
            return
 
        admin = SuperAdminUser(username=username, nome='Erick Amorim')
        admin.set_senha(senha)
        admin.save()
 
        self.stdout.write(self.style.SUCCESS(
            f'Super Admin "{username}" criado com sucesso!'
        ))
 