# 💅 Sistema de Agendamento — Salão de Unhas

Sistema web para gerenciamento de agendamentos de um salão de beleza, com painel administrativo completo, área do cliente e notificações internas.

---

## 🚀 Tecnologias

- **Backend:** Python 3 · Django 4
- **Banco de dados:** PostgreSQL (produção) · SQLite (desenvolvimento)
- **Frontend:** HTML5 · CSS3 · Bootstrap 5.3 · Bootstrap Icons
- **Hospedagem:** Render
- **Outros:** WhiteNoise · dj-database-url

---

## ✨ Funcionalidades

### Área da cliente
- Cadastro e login com autenticação nativa do Django
- Recuperação de senha por telefone
- Agendamento de serviços com seleção de data e horário disponível
- Visualização e cancelamento dos próprios agendamentos
- Pop-up automático de aviso quando um agendamento é removido pela administração
- Página de perfil, serviços, suporte e tutorial

### Painel administrativo
- Dashboard com resumo do dia
- Listagem de próximos agendamentos com filtro por data
- Exclusão de agendamentos com confirmação e notificação automática à cliente
- Atualização de status por agendamento (pendente / presente / ausente)
- Relatório financeiro dos últimos 31 dias
- Gerenciamento completo de serviços (criar, editar, excluir)
- Serviços com opção de ocupar dois horários consecutivos
- Gerenciamento de horários: bloquear, desbloquear e criar exceções por dia
- Listagem de clientes com opção de bloquear e desbloquear acesso
- Exclusão de clientes

### Notificações internas
- Quando o admin exclui um agendamento, uma notificação é criada para a cliente
- Na próxima vez que a cliente acessar `/home/`, um modal é exibido automaticamente com os detalhes do agendamento removido
- A notificação é exibida apenas uma vez e marcada como visualizada via AJAX

---

## 🗂️ Estrutura do projeto

```
agendamento_project/
├── agendamento/
│   ├── migrations/
│   ├── templates/
│   │   ├── admin/          # Templates do painel administrativo
│   │   └── clients/        # Templates da área da cliente
│   ├── models.py           # Cliente, Agendamento, Servico, HorarioBloqueado, NotificacaoExclusao
│   ├── views.py
│   ├── urls.py
│   ├── forms.py
│   ├── utils.py
│   └── tests.py
├── agendamento_project/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── manage.py
```

---

## ⚙️ Configuração local

**1. Clone o repositório**
```bash
git clone https://github.com/erickamorimtrindade/agendamento_project.git
cd agendamento_project
```

**2. Crie e ative o ambiente virtual**
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

**3. Instale as dependências**
```bash
pip install -r requirementes.txt
```

**4. Configure as variáveis de ambiente**

Crie um arquivo `.env` na raiz com:
```env
SECRET_KEY=sua_secret_key_aqui
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
```

**5. Execute as migrations**
```bash
python manage.py migrate
```

**6. Crie o superusuário**
```bash
python manage.py createsuperuser
```

**7. Rode o servidor**
```bash
python manage.py runserver
```

Acesse em `http://127.0.0.1:8000/`

---

## 🔐 Permissões

| Ação | Cliente | Admin |
|---|---|---|
| Criar agendamento | ✅ | — |
| Cancelar próprio agendamento | ✅ | — |
| Excluir qualquer agendamento | ❌ | ✅ |
| Gerenciar serviços | ❌ | ✅ |
| Gerenciar horários | ❌ | ✅ |
| Bloquear/desbloquear clientes | ❌ | ✅ |
| Ver relatórios | ❌ | ✅ |

---

## 📦 Deploy (Render)

O projeto está configurado para deploy direto no Render com PostgreSQL.

Variáveis de ambiente necessárias no painel do Render:

```
SECRET_KEY
DATABASE_URL
ALLOWED_HOSTS
DEBUG=False
```

O WhiteNoise já está configurado para servir arquivos estáticos sem necessidade de servidor externo.

---

## 👨‍💻 Autores

Desenvolvido por Erick Amorim e Rafael Maia

[LinkedIn] [https://www.linkedin.com/in/erickamorimtrindade/]
[GitHub] [https://github.com/erickamorimtrindade]

[LinkedIn] [https://www.linkedin.com/in/rafaelolimpiomaia/]
[GitHub] [https://github.com/rafaelolimpioo]