from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('projects/new/', views.project_create, name='project_create'),
    path('projects/<int:pk>/', views.project_detail, name='project_detail'),
    path('projects/<int:pk>/team/', views.team, name='project_team'),
    path('projects/<int:pk>/edit/', views.project_edit, name='project_edit'),
    path('projects/<int:pk>/modules/add/', views.module_add, name='module_add'),
    path('projects/<int:pk>/modules/<int:module_id>/submodules/add/', views.submodule_add, name='submodule_add'),
]
