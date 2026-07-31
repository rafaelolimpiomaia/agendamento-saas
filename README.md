# ✂️ Agendamento Digital — Sistema SaaS de Agendamentos

Sistema web multi-tenant para gerenciamento de agendamentos de salões de beleza, barbearias, esmalterias e similares. Cada estabelecimento tem seu próprio painel isolado, área de clientes personalizada e identidade visual configurável.

---

## 🚀 Tecnologias

| Camada | Tecnologias |
|---|---|
| Backend | Python 3.14 · Django 6 |
| Banco de dados | PostgreSQL (produção) · SQLite (desenvolvimento) |
| Frontend | HTML5 · CSS3 · Bootstrap 5.3 · Bootstrap Icons |
| Hospedagem | Render |
| Outros | WhiteNoise · dj-database-url · python-dotenv |

---

## ✨ Funcionalidades

### 🌐 Páginas Públicas
- Landing page com apresentação do produto, preços e FAQ
- Cadastro de salão com código de convite obrigatório
- Login direto pelo slug do salão na landing page
- Geração automática de slug a partir do nome do salão
- Termos de uso e política de privacidade

### 👤 Área do Cliente
- Cadastro e login isolados por salão (mesmo username pode existir em salões diferentes)
- Recuperação de senha por nome de usuário + telefone
- Escolha de serviço com preço e duração exibidos
- Agendamento com seleção de data e horário disponível
- Regra de 24h de antecedência mínima
- Visualização e cancelamento dos próprios agendamentos
- Pop-up automático quando um agendamento é removido pelo admin
- Páginas de perfil, sobre, suporte e tutorial

### 🛠️ Painel Administrativo
- Dashboard com resumo do dia
- Calendário mensal estilo Google Calendar
- Listagem de próximos agendamentos com filtro por data
- Agendamento manual sem exigir conta do cliente
- Atualização de status por agendamento (pendente / presente / ausente)
- Exclusão de agendamento com notificação automática ao cliente
- Relatório financeiro dos últimos 31 dias com gráficos
- Gerenciamento completo de serviços (criar, editar, excluir, ativar/desativar)
- Serviços com opção de ocupar dois horários consecutivos (horário duplo)
- Gerenciamento pontual de horários: bloquear, desbloquear e liberar exceções
- Listagem de clientes com histórico de agendamentos e ausências
- Bloqueio e desbloqueio de clientes

### 🎨 Personalização por Salão
- Nome de exibição, tipo de estabelecimento, público atendido
- Endereço com link automático para Google Maps
- Telefone com link para WhatsApp
- Instagram com link para o perfil
- Cor principal do site aplicada em toda a área do cliente
- Horários de funcionamento configuráveis por dia da semana (grade de 30 em 30 minutos, de 00:00 a 23:30)
- Períodos de bloqueio para férias e feriados

### 🔑 Controle de Acesso
- Código de convite obrigatório para cadastro de novos salões
- Geração e gestão de códigos pelo Painel Master

### 🛡️ Painel Master (Super Admin)
- Autenticação completamente isolada do sistema dos salões
- Dashboard global com métricas de todos os salões
- Listagem, busca e filtro de salões por status
- Congelamento de salões (bloqueia novos agendamentos, admin continua com acesso)
- Suspensão de salões (bloqueia acesso total)
- Reativação de salões
- Exclusão lógica (soft delete) com confirmação obrigatória
- Histórico de ações administrativas por salão
- Gestão de códigos de ativação com geração em lote

### 🔔 Notificações Internas
- Notificação criada quando o admin exclui agendamento de cliente cadastrado
- Modal automático exibido no próximo acesso do cliente
- Marcada como visualizada via AJAX — exibida apenas uma vez

---

## 🗂️ Estrutura do Projeto

```
agendamento-saas/
├── agendamento_project/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── agendamento/
│   ├── migrations/
│   ├── templates/
│   │   ├── admin/          # Templates do painel administrativo
│   │   ├── clients/        # Templates da área do cliente
│   │   └── public/         # Landing, cadastro, termos
│   ├── static/
│   ├── models.py           # Tenant, Cliente, Agendamento, Servico,
│   │                       # HorarioBloqueado, NotificacaoExclusao,
│   │                       # CodigoConvite, ConfiguracaoSalao,
│   │                       # HorarioFuncionamento, PeriodoBloqueio
│   ├── views.py
│   ├── views_public.py
│   ├── urls.py
│   ├── forms.py
│   ├── utils.py
│   ├── middleware.py
│   ├── context_processors.py
│   └── decorators.py
├── master/
│   ├── templates/master/   # Templates do Painel Master
│   ├── models.py           # SuperAdminUser, StatusSalao, LogAdministrativo
│   ├── views.py
│   ├── urls.py
│   └── decorators.py
└── manage.py
```

---

## ⚙️ Configuração Local

### 1. Clone o repositório
```bash
git clone https://github.com/erickamorimtrindade/agendamento-saas.git
cd agendamento-saas/agendamento_project
```

### 2. Crie e ative o ambiente virtual
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Instale as dependências
```bash
pip install -r requirements.txt
```

### 4. Configure as variáveis de ambiente
Crie um arquivo `.env` na raiz com:
```env
SECRET_KEY=sua_secret_key_aqui
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
```

### 5. Execute as migrations
```bash
python manage.py migrate
```

### 6. Crie o Super Admin do Painel Master
```bash
python manage.py shell
```
```python
from master.models import SuperAdminUser
admin = SuperAdminUser(username='seu_usuario', nome='Seu Nome')
admin.set_senha('sua_senha')
admin.save()
```

### 7. Gere um código de ativação para o primeiro salão
```bash
python manage.py shell
```
```python
from agendamento.models import CodigoConvite
c = CodigoConvite.gerar()
print(c.codigo)
```

### 8. Rode o servidor
```bash
python manage.py runserver
```

| URL | Descrição |
|---|---|
| `http://127.0.0.1:8000/` | Landing page |
| `http://127.0.0.1:8000/cadastro/` | Cadastro de novo salão |
| `http://127.0.0.1:8000/<slug>/` | Área do cliente |
| `http://127.0.0.1:8000/<slug>/painel/` | Painel do admin do salão |
| `http://127.0.0.1:8000/master/` | Painel Master |

---

## 🔐 Permissões

| Ação | Cliente | Admin do Salão | Super Admin |
|---|---|---|---|
| Criar agendamento | ✅ | — | — |
| Cancelar próprio agendamento | ✅ | — | — |
| Excluir qualquer agendamento | ❌ | ✅ | — |
| Gerenciar serviços | ❌ | ✅ | — |
| Gerenciar horários | ❌ | ✅ | — |
| Personalizar salão | ❌ | ✅ | — |
| Bloquear/desbloquear clientes | ❌ | ✅ | — |
| Ver relatórios | ❌ | ✅ | — |
| Congelar/suspender salões | ❌ | ❌ | ✅ |
| Gerar códigos de ativação | ❌ | ❌ | ✅ |
| Ver todos os salões | ❌ | ❌ | ✅ |

---

## 📦 Deploy (Render)

O projeto está configurado para deploy direto no Render com PostgreSQL gerenciado.

Variáveis de ambiente necessárias:
```
SECRET_KEY=
DATABASE_URL=
ALLOWED_HOSTS=
DEBUG=False
```

O WhiteNoise já está configurado para servir arquivos estáticos sem necessidade de servidor externo.

---

## 👨‍💻 Autores

Desenvolvido por **Erick Amorim** e **Rafael Maia**

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Erick-blue)](https://www.linkedin.com/in/erickamorimtrindade/)
[![GitHub](https://img.shields.io/badge/GitHub-Erick-black)](https://github.com/erickamorimtrindade)

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Rafael-blue)](https://www.linkedin.com/in/rafaelolimpiomaia/)
[![GitHub](https://img.shields.io/badge/GitHub-Rafael-black)](https://github.com/rafaelolimpioo)
