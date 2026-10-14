from django.conf import settings
from django.db import models, transaction
from django.db.models import Max

from projects.models import Module, Project, SubModule
from runs.models import TestResult, TestRun
from testcases.models import TestCase


class Bug(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        IN_PROGRESS = 'in_progress', 'In progress'
        FIXED = 'fixed', 'Fixed'
        RETEST = 'retest', 'Retest'
        CLOSED = 'closed', 'Closed'
        REOPENED = 'reopened', 'Reopened'

    class Severity(models.TextChoices):
        CRITICAL = 'critical', 'Critical'
        MAJOR = 'major', 'Major'
        MINOR = 'minor', 'Minor'
        TRIVIAL = 'trivial', 'Trivial'

    class Priority(models.TextChoices):
        HIGH = 'high', 'High'
        MEDIUM = 'medium', 'Medium'
        LOW = 'low', 'Low'

    class Layer(models.TextChoices):
        BACKEND = 'backend', 'Backend'
        FRONTEND = 'frontend', 'Frontend'
        BOTH = 'both', 'Frontend & Backend'

    class CloseReason(models.TextChoices):
        FIXED = 'fixed', 'Fixed'
        NOT_A_BUG = 'not_a_bug', 'Not a bug'
        DUPLICATE = 'duplicate', 'Duplicate'
        WONT_FIX = 'wont_fix', "Won't fix"
        DEFERRED = 'deferred', 'Deferred'
        CANNOT_REPRODUCE = 'cannot_reproduce', 'Cannot reproduce'
        NOT_REQUIRED = 'not_required', 'Not required (BA decision)'

    class Phase(models.TextChoices):
        QA = 'qa', 'Found in QA'
        PRODUCTION = 'production', 'Found in production'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='bugs')
    number = models.PositiveIntegerField(editable=False)
    title = models.CharField(max_length=300)
    module = models.ForeignKey(Module, on_delete=models.PROTECT, related_name='bugs')
    sub_module = models.ForeignKey(SubModule, on_delete=models.PROTECT, null=True, blank=True, related_name='bugs')
    test_case = models.ForeignKey(TestCase, on_delete=models.SET_NULL, null=True, blank=True, related_name='bugs')
    run = models.ForeignKey(TestRun, on_delete=models.SET_NULL, null=True, blank=True, related_name='bugs')
    result = models.ForeignKey(TestResult, on_delete=models.SET_NULL, null=True, blank=True, related_name='bugs')
    steps = models.TextField()
    expected_result = models.TextField()
    actual_result = models.TextField(blank=True)   # optional: a tester can fill it in later
    layer = models.CharField(max_length=10, choices=Layer.choices, default=Layer.FRONTEND)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MAJOR)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    environment = models.CharField(max_length=60, blank=True)
    build = models.CharField(max_length=60, blank=True)
    release_phase = models.CharField(max_length=12, choices=Phase.choices, default=Phase.QA)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    close_reason = models.CharField(max_length=20, choices=CloseReason.choices, blank=True)
    reopen_count = models.PositiveIntegerField(default=0)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='assigned_bugs')
    co_assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='co_assigned_bugs')   # second developer when the bug is Frontend & Backend
    # Names are copied as TEXT when a bug is fixed / ruled out, so later team changes never rewrite history.
    solved_by_backend = models.CharField(max_length=150, blank=True, default='')
    solved_by_frontend = models.CharField(max_length=150, blank=True, default='')
    ba_name = models.CharField(max_length=150, blank=True, default='')
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                 related_name='reported_bugs')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-number']
        constraints = [models.UniqueConstraint(fields=['project', 'number'], name='unique_bug_number')]

    @property
    def code(self):
        return f'BUG-{self.number}'

    def save(self, *args, **kwargs):
        if not self.number:
            with transaction.atomic():
                last = Bug.objects.filter(project=self.project).aggregate(m=Max('number'))['m'] or 0
                self.number = last + 1
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} {self.title}'


class BugComment(models.Model):
    bug = models.ForeignKey(Bug, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class BugHistory(models.Model):
    """An append-only diary of everything that happened to a bug."""
    bug = models.ForeignKey(Bug, on_delete=models.CASCADE, related_name='history')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    field = models.CharField(max_length=40)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    LABELS = {'layer': 'developer type', 'co-assignee': 'second developer'}

    @property
    def field_label(self):
        return self.LABELS.get(self.field, self.field)

    class Meta:
        ordering = ['-created_at', '-id']
