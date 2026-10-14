from django.shortcuts import get_object_or_404
from .models import Project


def project_for(user, pk):
    """Fetch a project only if this user may see it (otherwise 404)."""
    return get_object_or_404(Project.objects.visible_to(user), pk=pk)
