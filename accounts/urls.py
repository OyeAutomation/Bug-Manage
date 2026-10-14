from django.urls import path
from . import views

urlpatterns = [path('theme/', views.toggle_theme, name='toggle_theme')]
