from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import Agendamento, Tenant, Servico, CodigoConvite
from datetime import date, time, datetime
from django.utils.text import slugify


class CadastroSalaoForm(forms.Form):
    # ── Seção 1: Estabelecimento ──────────────────────────────
    nome_salao = forms.CharField(
        label='Nome do salão',
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Salão da Maria',
            'id': 'id_nome_salao',
        })
    )
    tipo_negocio = forms.ChoiceField(
        label='Tipo de negócio',
        choices=[
            ('salao',     'Salão de Beleza'),
            ('barbearia', 'Barbearia'),
            ('studio',    'Studio de Unhas'),
            ('outro',     'Outro'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    slug = forms.SlugField(
        label='Nome de acesso no sistema',
        max_length=60,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'id_slug',
            'placeholder': 'salao-da-maria',
        })
    )

    # ── Seção 2: Dono ─────────────────────────────────────────
    nome_responsavel = forms.CharField(
        label='Nome do proprietário',
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Seu nome completo',
        })
    )
    telefone = forms.CharField(
        label='Telefone',
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '(83) 90000-0000',
            'id': 'id_telefone',
        })
    )
    email = forms.EmailField(
        label='E-mail',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'seu@email.com',
        })
    )
    # ── Codigo de Convite ────────────────────────────────────────
    codigo_convite = forms.CharField(
        label='Código de acesso',
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Código fornecido no momento da contratação',
        })
    )   
    # ── Seção 3: Conta ────────────────────────────────────────
    senha = forms.CharField(
        label='Senha',
        min_length=6,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mínimo 6 caracteres',
            'id': 'id_senha',
        })
    )
    confirmar_senha = forms.CharField(
        label='Confirmar senha',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Repita sua senha',
            'id': 'id_confirmar_senha',
        })
    )
    termos = forms.BooleanField(
        label='Li e aceito os Termos de Uso',
        error_messages={'required': 'Você precisa aceitar os termos para continuar.'},
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    def clean_codigo_convite(self):
        codigo = self.cleaned_data.get('codigo_convite', '').strip()
        try:
            convite = CodigoConvite.objects.get(codigo=codigo, usado=False)
        except CodigoConvite.DoesNotExist:
            raise forms.ValidationError('Código inválido ou já utilizado.')
        return codigo

    def clean_slug(self):
        slug = self.cleaned_data.get('slug')
        if Tenant.objects.filter(slug=slug).exists():
            raise forms.ValidationError('Este endereço já está em uso. Escolha outro.')
        return slug

    def clean_nome_responsavel(self):
        nome = self.cleaned_data.get('nome_responsavel')
        if User.objects.filter(username=nome).exists():
            raise forms.ValidationError('Já existe uma conta com este nome.')
        return nome
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Este e-mail já está cadastrado.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        senha = cleaned_data.get('senha')
        confirmar = cleaned_data.get('confirmar_senha')
        if senha and confirmar and senha != confirmar:
            self.add_error('confirmar_senha', 'As senhas não coincidem.')
        return cleaned_data

class AgendamentoForm(forms.ModelForm):
    class Meta:
        model = Agendamento
        fields = ['data', 'horario', 'descricao']
        widgets = {
            'data': forms.DateInput(attrs={
                'type': 'text',
                'onchange': 'this.form.submit()',
                'class': 'form-control',
                'id': 'data',
                'min': date.today().isoformat(),
            }),
            'horario': forms.HiddenInput(),
            'descricao': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Digite uma descrição para o agendamento',
                'rows': 4,
            }),
        }
        labels = {
            'data': 'Data',
            'descricao': 'Descrição',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['horario'].required = False

    def clean_data(self):
        data = self.cleaned_data.get('data')
        if not data:
            raise forms.ValidationError("Selecione uma data.")
        return data

    def clean_horario(self):
        horario = self.cleaned_data.get('horario')
        if not horario:
            raise forms.ValidationError('Selecione um horário antes de agendar.')
        return horario

    def clean(self):
        cleaned_data = super().clean()
        data = cleaned_data.get('data')
        horario = cleaned_data.get('horario')

        if data and data < date.today():
            raise forms.ValidationError("Não é possível agendar em datas passadas.")

        if horario:
            if horario < time(8, 0) or horario > time(22, 0):
                raise forms.ValidationError("Horário permitido apenas entre 08:00 e 22:00.")

        if data and horario and Agendamento.objects.filter(data=data, horario=horario).exists():
            raise forms.ValidationError("Este horário já está ocupado.")

        return cleaned_data


class IdentificarUsuarioForm(forms.Form):
    nome = forms.CharField(
        label="Nome do usuário",
        max_length=100,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Digite seu nome",
            "autofocus": True,
        })
    )
    telefone = forms.CharField(
        label="Telefone cadastrado",
        max_length=15,
        widget=forms.TextInput(attrs={
            "placeholder": "Ex: (83) 90000-0000",
            "class": "form-control",
            "id": "id_telefone_recuperar",
        })
    )


class RedefinirSenhaForm(forms.Form):
    nova_senha = forms.CharField(
        label="Nova senha",
        min_length=5,
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Mínimo 5 caracteres",
        })
    )
    confirmar_senha = forms.CharField(
        label="Confirmar nova senha",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Repita a nova senha",
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        nova = cleaned_data.get("nova_senha")
        confirmar = cleaned_data.get("confirmar_senha")
        if nova and confirmar and nova != confirmar:
            self.add_error("confirmar_senha", "As senhas não coincidem. Digite novamente.")
        return cleaned_data


class AgendamentoManualForm(forms.Form):
    """
    Formulário para criação de agendamentos manuais pelo administrador.
    Não cria conta de usuário nem exige cadastro de cliente.
    """
    nome = forms.CharField(
        label='Nome da cliente',
        max_length=40,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nome completo',
            'autofocus': True,
        }),
    )
    telefone = forms.CharField(
        label='Telefone',
        max_length=15,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '(83) 90000-0000',
        }),
    )
    servico = forms.ModelChoiceField(
        label='Serviço',
        queryset=Servico.objects.none(),  # começa vazio, preenchido no __init__
        empty_label='— Selecione um serviço —',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    data = forms.DateField(
        label='Data',
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'min': date.today().isoformat(),
        }),
    )
    horario = forms.TimeField(
        label='Horário',
        widget=forms.Select(attrs={'class': 'form-select'}),
        input_formats=['%H:%M'],
    )
    descricao = forms.CharField(
        label='Observações (opcional)',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Anotações sobre o atendimento…',
        }),
    )

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        horarios_disponiveis = kwargs.pop('horarios_disponiveis', [])
        super().__init__(*args, **kwargs)

        if tenant:
            self.fields['servico'].queryset = Servico.objects.filter(
                tenant=tenant, ativo=True
            )

        choices = [('', '— Selecione a data primeiro —')]
        if horarios_disponiveis:
            choices = [(h, h) for h in horarios_disponiveis]
        self.fields['horario'].widget.choices = choices

class ConfiguracaoSalaoForm(forms.Form):
    nome_exibicao = forms.CharField(
        label='Nome de exibição do estabelecimento',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Salão da Maria, Barbearia do João...',
        })
    )
    tipo_negocio = forms.ChoiceField(
        label='Tipo de estabelecimento',
        choices=[
            ('',           '— Selecione —'),
            ('salao',      'Salão de Beleza'),
            ('barbearia',  'Barbearia'),
            ('studio',     'Studio de Unhas'),
            ('esmalteria', 'Esmalteria'),
            ('outro',      'Outro'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    telefone = forms.CharField(
        label='Telefone para contato',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '(83) 90000-0000',
            'id': 'id_telefone_config',
        })
    )
    publico = forms.ChoiceField(
        label='Público atendido',
        choices=[
            ('homens',   'Homens'),
            ('mulheres', 'Mulheres'),
            ('ambos',    'Homens e Mulheres'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    endereco = forms.CharField(
        label='Endereço',
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Rua das Flores, 123 — Centro, João Pessoa - PB',
        })
    )
    instagram = forms.CharField(
        label='Instagram',
        max_length=60,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '@seu.perfil',
        })
    )
    cor_primaria = forms.CharField(
        label='Cor principal do site',
        max_length=7,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'type': 'color',
        })
    )