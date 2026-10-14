from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Our own user model: Django's user plus a role and a theme choice."""
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        MANAGER = 'manager', 'Manager'
        QA = 'qa', 'QA'
        BA = 'ba', 'Business analyst'
        DEVELOPER = 'developer', 'Developer'

    class Theme(models.TextChoices):
        LIGHT = 'light', 'Light'
        DARK = 'dark', 'Dark'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.QA)
    theme = models.CharField(max_length=5, choices=Theme.choices, default=Theme.LIGHT)

    def save(self, *args, **kwargs):
        if self.is_superuser:          # the first superuser is always an Admin
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    def has_role(self, *roles):
        return self.role in roles

    @property
    def is_editor(self):
        return self.role in (self.Role.ADMIN, self.Role.MANAGER, self.Role.QA)

    @property
    def can_edit_cases(self):
        return self.role in (self.Role.ADMIN, self.Role.MANAGER, self.Role.QA, self.Role.BA)

    @property
    def can_manage_projects(self):
        return self.role in (self.Role.ADMIN, self.Role.MANAGER)
