from django.urls import path
from . import views

urlpatterns = [
    path('', views.case_list, name='case_list'),
    path('new/', views.case_create, name='case_create'),
    path('quick-add/', views.quick_add, name='quick_add'),
    path('export.csv', views.export_csv, name='cases_export'),
    path('bulk/', views.bulk_action, name='cases_bulk'),
    path('import/', views.import_home, name='import_home'),
    path('import/template.xlsx', views.import_template, name='import_template'),
    path('import/<int:pk>/', views.import_detail, name='import_detail'),
    path('import/<int:pk>/confirm/', views.import_confirm, name='import_confirm'),
    path('import/<int:pk>/cancel/', views.import_cancel, name='import_cancel'),
    path('import/<int:pk>/errors.xlsx', views.import_errors, name='import_errors'),
    path('<int:pk>/edit/', views.case_edit, name='case_edit'),
    path('<int:pk>/delete/', views.case_delete, name='case_delete'),
    path('<int:pk>/clone/', views.case_clone, name='case_clone'),
]
