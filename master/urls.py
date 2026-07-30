from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.master_login, name='master_login'),
    path('logout/', views.master_logout, name='master_logout'),
    path('', views.master_dashboard, name='master_dashboard'),

    path('saloes/', views.listar_saloes, name='master_listar_saloes'),
    path('saloes/<int:tenant_id>/', views.detalhes_salao, name='master_detalhes_salao'),
    path('saloes/<int:tenant_id>/congelar/', views.congelar_salao, name='master_congelar_salao'),
    path('saloes/<int:tenant_id>/reativar/', views.reativar_salao, name='master_reativar_salao'),
    path('saloes/<int:tenant_id>/suspender/', views.suspender_salao, name='master_suspender_salao'),
    path('saloes/<int:tenant_id>/excluir/', views.excluir_salao, name='master_excluir_salao'),

    path('codigos/', views.codigos_ativacao, name='master_codigos_ativacao'),
]