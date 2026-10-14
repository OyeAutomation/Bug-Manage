from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/', include('accounts.urls')),
    path('projects/<int:project_id>/cases/', include('testcases.urls')),
    path('projects/<int:project_id>/runs/', include('runs.urls')),
    path('projects/<int:project_id>/bugs/', include('bugs.urls')),
    path('', include('projects.urls')),
]
