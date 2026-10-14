from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_POST

from .utils import safe_next


@login_required
@require_POST
def toggle_theme(request):
    user = request.user
    user.theme = 'dark' if user.theme == 'light' else 'light'
    user.save(update_fields=['theme'])
    return HttpResponseRedirect(safe_next(request, 'dashboard'))
