from django.urls import path
from . import views

urlpatterns = [
    path('', views.bug_list, name='bug_list'),
    path('new/', views.bug_create, name='bug_create'),
    path('export.csv', views.bug_export, name='bugs_export'),
    path('<int:pk>/', views.bug_detail, name='bug_detail'),
    path('<int:pk>/edit/', views.bug_edit, name='bug_edit'),
    path('<int:pk>/status/', views.bug_status, name='bug_status'),
    path('<int:pk>/layer/', views.bug_layer, name='bug_layer'),
    path('<int:pk>/assign/', views.bug_assign, name='bug_assign'),
    path('<int:pk>/comment/', views.bug_comment, name='bug_comment'),
]
