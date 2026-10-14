from django.contrib import admin
from .models import Bug, BugComment, BugHistory

admin.site.register(Bug)
admin.site.register(BugComment)
admin.site.register(BugHistory)
