from django.urls import path
from . import views

urlpatterns = [
    path('', views.run_list, name='run_list'),
    path('new/', views.run_create, name='run_create'),
    path('export.csv', views.run_list_export, name='run_list_export'),
    path('<int:pk>/export.csv', views.run_export, name='run_export'),
    path('<int:pk>/', views.run_detail, name='run_detail'),
    path('<int:pk>/execute/<int:rid>/', views.run_execute, name='run_execute'),
    path('<int:pk>/result/<int:rid>/', views.run_set_result, name='run_set_result'),
    path('<int:pk>/close/', views.run_close, name='run_close'),
    path('<int:pk>/reopen/', views.run_reopen, name='run_reopen'),
]
