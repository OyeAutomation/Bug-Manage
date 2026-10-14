from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('QA Tracker', {'fields': ('role', 'theme')}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('QA Tracker', {'fields': ('role',)}),)
    list_display = ('username', 'first_name', 'last_name', 'role', 'is_active')
    list_filter = ('role', 'is_active')
    list_editable = ('role',)      # fix a wrong role right from the list; new users default to QA
