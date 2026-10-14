from django.contrib import admin
from .models import Project, Module, SubModule

admin.site.register(Project)
admin.site.register(Module)
admin.site.register(SubModule)
