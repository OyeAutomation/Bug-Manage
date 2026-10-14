from functools import wraps
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Block a view unless the logged-in user has one of the given roles."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.has_role(*roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
