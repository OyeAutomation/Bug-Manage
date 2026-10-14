from django.contrib import admin
from .models import TestResult, TestRun

admin.site.register(TestRun)
admin.site.register(TestResult)
