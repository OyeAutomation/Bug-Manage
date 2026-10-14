import datetime

from django.conf import settings
from django.db import models
from django.db.models import Case, Count, IntegerField, Value, When

from projects.models import Project
from testcases.models import TestCase


class TestRun(models.Model):
    """One round of testing, for example 'Sprint 18 Regression' on build 2.4.0."""
    __test__ = False

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        CLOSED = 'closed', 'Closed'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='runs')
    name = models.CharField(max_length=150)
    run_date = models.DateField(default=datetime.date.today)
    build = models.CharField(max_length=60, blank=True)      # shown as 'Version'
    assigned_qa = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    environment = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def sync_cases(self):
        """Add every active test case that is not in this run yet (new cases appear in open runs)."""
        have = set(self.results.values_list('test_case_id', flat=True))
        missing = list(self.project.test_cases.filter(archived=False).exclude(pk__in=have))
        TestResult.objects.bulk_create([TestResult(run=self, test_case=c) for c in missing])
        return len(missing)

    def summary(self):
        counts = dict(self.results.order_by().values_list('result').annotate(n=Count('id')))
        total = sum(counts.values())
        done = counts.get('pass', 0) + counts.get('fail', 0) + counts.get('blocked', 0)   # skipped cases are not finished
        return {'total': total, 'done': done, 'pass': counts.get('pass', 0), 'fail': counts.get('fail', 0),
                'blocked': counts.get('blocked', 0), 'skip': counts.get('skip', 0),
                'not_run': counts.get('not_run', 0), 'percent': round(100 * done / total) if total else 0}


class TestResultQuerySet(models.QuerySet):
    def ordered(self):
        """Test case order, but skipped cases go to the very end of the run."""
        return self.annotate(skip_rank=Case(When(result='skip', then=Value(1)), default=Value(0), output_field=IntegerField())
                             ).order_by('skip_rank', 'test_case__number')


class TestResult(models.Model):
    """The outcome of ONE test case inside ONE run. Created as 'not run' when the run is created."""
    __test__ = False

    class Result(models.TextChoices):
        NOT_RUN = 'not_run', 'Not run'
        PASS = 'pass', 'Pass'
        FAIL = 'fail', 'Fail'
        BLOCKED = 'blocked', 'Blocked'
        SKIP = 'skip', 'Skipped'

    run = models.ForeignKey(TestRun, on_delete=models.CASCADE, related_name='results')
    test_case = models.ForeignKey(TestCase, on_delete=models.PROTECT, related_name='results')
    result = models.CharField(max_length=10, choices=Result.choices, default=Result.NOT_RUN)
    note = models.TextField(blank=True)
    tester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    executed_at = models.DateTimeField(null=True, blank=True)

    objects = TestResultQuerySet.as_manager()

    class Meta:
        ordering = ['test_case__number']
        constraints = [models.UniqueConstraint(fields=['run', 'test_case'], name='one_result_per_case_per_run')]
