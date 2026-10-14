from django.conf import settings
from django.db import models


class ProjectQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Admins see every project; everyone else sees only projects they belong to."""
        if user.role == 'admin':
            return self
        return self.filter(members=user)


class Project(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='projects', blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # The project team. Bugs are assigned to these people by layer.
    backend_dev = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    frontend_dev = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    ba = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Module(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='modules')
    name = models.CharField(max_length=120)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['project', 'name'], name='unique_module_per_project')]

    def __str__(self):
        return f'{self.project} / {self.name}'


class SubModule(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='submodules')
    name = models.CharField(max_length=120)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['module', 'name'], name='unique_submodule_per_module')]

    def __str__(self):
        return f'{self.module} / {self.name}'


class TeamChange(models.Model):
    """Who held each team role before and after a change. Names are copied as text on purpose."""
    class Role(models.TextChoices):
        BACKEND = 'backend', 'Backend developer'
        FRONTEND = 'frontend', 'Frontend developer'
        BA = 'ba', 'Business analyst'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='team_changes')
    role = models.CharField(max_length=10, choices=Role.choices)
    old_name = models.CharField(max_length=150, blank=True)
    new_name = models.CharField(max_length=150, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
