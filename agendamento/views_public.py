from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import login, authenticate
from .models import Tenant, CodigoConvite
from .forms import CadastroSalaoForm
from django.utils import timezone


def landing(request):
    """Página inicial pública — apresenta o produto."""
    return render(request, 'public/landing.html')


def cadastro_salao(request):
    """
    Fluxo de autocadastro do salão.
    Cria Tenant + User admin automaticamente.
    """
    form = CadastroSalaoForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        nome_salao  = form.cleaned_data['nome_salao']
        slug        = form.cleaned_data['slug']
        telefone    = form.cleaned_data['telefone']
        cnpj        = form.cleaned_data.get('cnpj', '')
        nome_resp   = form.cleaned_data['nome_responsavel']
        email       = form.cleaned_data['email']
        senha       = form.cleaned_data['senha']

        # 1. Cria o usuário administrador
        user = User.objects.create_user(
            username=nome_resp,
            email=email,
            password=senha,
            first_name=nome_resp,
            is_staff=True,
        )

        # 2. Cria o Tenant vinculado ao admin
        tenant = Tenant.objects.create(
            nome=nome_salao,
            slug=slug,
            tipo_negocio=form.cleaned_data['tipo_negocio'],
            nome_responsavel=form.cleaned_data['nome_responsavel'],
            telefone=telefone,
            email=email,
            admin=user,
            termos_aceitos=True,
            termos_aceitos_em=timezone.now(),
        )

        #Codigo confirmação
        codigo = form.cleaned_data['codigo_convite']
        convite = CodigoConvite.objects.get(codigo=codigo, usado=False)
        convite.usado = True
        convite.usado_por = tenant
        convite.save()

        # 3. Loga o admin automaticamente
        login(request, user)

        # 4. Redireciona para o onboarding do salão
        return redirect('onboarding', tenant_slug=slug)

    return render(request, 'public/cadastro_salao.html', {'form': form})


def onboarding(request, tenant_slug):
    """
    Wizard pós-cadastro: configura serviços, horários, funcionárias.
    Só pode ser acessado pelo admin do salão recém-criado.
    """
    tenant = request.tenant  # já resolvido pelo middleware
    return render(request, 'admin/onboarding.html', {'tenant': tenant})

def login_proprietario(request):
    if request.method == 'POST':
        slug = request.POST.get('slug', '').strip()
        senha = request.POST.get('senha', '').strip()

        try:
            tenant = Tenant.objects.get(slug=slug, ativo=True)
        except Tenant.DoesNotExist:
            return render(request, 'public/landing.html', {
                'erro_login': 'Salão não encontrado.'
            })

        user = authenticate(request, username=tenant.admin.username, password=senha)

        if user and user.is_staff:
            login(request, user)
            return redirect('painel_admin', tenant_slug=slug)

        return render(request, 'public/landing.html', {
            'erro_login': 'Senha incorreta.'
        })

    return redirect('landing')