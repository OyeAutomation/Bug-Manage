from django.conf import settings
from django.db import models, transaction
from django.db.models import Max

from projects.models import Module, Project, SubModule


class TestCase(models.Model):
    __test__ = False  # stop Django's test runner mistaking this model for a test class

    class Layer(models.TextChoices):
        BACKEND = 'backend', 'Backend'
        FRONTEND = 'frontend', 'Frontend'
        BOTH = 'both', 'Frontend & Backend'

    class Priority(models.TextChoices):
        HIGH = 'high', 'High'
        MEDIUM = 'medium', 'Medium'
        LOW = 'low', 'Low'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='test_cases')
    number = models.PositiveIntegerField(editable=False)  # TC-1, TC-2 ... counted per project
    module = models.ForeignKey(Module, on_delete=models.PROTECT, related_name='test_cases')
    sub_module = models.ForeignKey(SubModule, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='test_cases')
    title = models.CharField(max_length=300)
    steps = models.TextField()
    expected_result = models.TextField()
    layer = models.CharField(max_length=10, choices=Layer.choices, default=Layer.FRONTEND)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['number']
        constraints = [models.UniqueConstraint(fields=['project', 'number'], name='unique_case_number')]

    @property
    def code(self):
        return f'TC-{self.number}'

    def save(self, *args, **kwargs):
        if not self.number:
            with transaction.atomic():
                last = TestCase.objects.filter(project=self.project).aggregate(m=Max('number'))['m'] or 0
                self.number = last + 1
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} {self.title}'


class ImportBatch(models.Model):
    """One Excel upload. It first sits in 'preview' (nothing saved to real test cases),
    then becomes 'done' after the user confirms. Done batches are the import history."""
    class Status(models.TextChoices):
        PREVIEW = 'preview', 'Preview'
        IMPORTING = 'importing', 'Importing'
        DONE = 'done', 'Done'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='import_batches')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    filename = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREVIEW)
    rows = models.JSONField(default=list)       # every parsed row with its status and errors
    policy = models.CharField(max_length=10, blank=True)   # what to do with duplicates: skip / update
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def count(self, status):
        return sum(1 for r in self.rows if r['status'] == status)
