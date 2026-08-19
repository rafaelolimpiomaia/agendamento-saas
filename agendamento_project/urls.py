"""
URL configuration for agendamento_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# agendamento_project/urls.py
from django.contrib import admin
from django.urls import path, include
import agendamento.views_public as public_views
from agendamento import views as agendamento_views

urlpatterns = [
    path('', public_views.landing, name='landing'),
    path('cadastro/', public_views.cadastro_salao, name='cadastro_salao'),
    path('entrar/', public_views.login_proprietario, name='login_proprietario'),
    path('termos/', public_views.termos, name='termos'),
    path('privacidade/', public_views.privacidade, name='privacidade'),
    path('admin/', admin.site.urls),
    path('master/', include('master.urls')),
    path('<slug:tenant_slug>/', include('agendamento.urls')),
    path('webhook/mercadopago/', agendamento_views.webhook_mercadopago, name='webhook_mercadopago'),
]

