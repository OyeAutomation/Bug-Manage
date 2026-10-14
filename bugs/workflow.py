"""The bug lifecycle rules. Everything about 'who may move a bug where' lives in this file."""
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Bug, BugHistory
from .team import solved_names

S = Bug.Status
ORDER = [S.OPEN, S.IN_PROGRESS, S.FIXED, S.RETEST, S.CLOSED, S.REOPENED]

# Which status can follow which (the shape of the lifecycle).
TRANSITIONS = {
    S.OPEN: {S.IN_PROGRESS, S.CLOSED},
    S.IN_PROGRESS: {S.OPEN, S.FIXED, S.CLOSED},
    S.FIXED: {S.RETEST, S.CLOSED, S.REOPENED},
    S.RETEST: {S.CLOSED, S.REOPENED},
    S.REOPENED: {S.IN_PROGRESS, S.FIXED, S.CLOSED},
    S.CLOSED: {S.REOPENED},
}
# Which statuses each role may set (developers can never close a bug).
ROLE_TARGETS = {
    'developer': {S.OPEN, S.IN_PROGRESS, S.FIXED},
    'qa': {S.RETEST, S.CLOSED, S.REOPENED},
    'manager': set(S), 'admin': set(S),
}
FIXED_STATES = (S.FIXED, S.RETEST)


def allowed_targets(status, role):
    options = TRANSITIONS[status] & ROLE_TARGETS.get(role, set())
    return [(s.value, s.label) for s in ORDER if s in options]


def log(bug, user, field, old='', new=''):
    BugHistory.objects.create(bug=bug, user=user, field=field, old_value=old, new_value=new)


def change_status(bug, user, target, reason='', seen_status=None):
    """Move a bug to a new status. Returns an error message, or None when it worked."""
    if seen_status and bug.status != seen_status:
        return 'Someone changed this bug while you were looking at it. Review the new status and try again.'
    if target not in dict(allowed_targets(bug.status, user.role)):
        return 'You cannot move this bug to that status.'
    close_reason = ''
    if target == S.CLOSED:
        if bug.status in FIXED_STATES:
            close_reason = reason or Bug.CloseReason.FIXED
        elif reason in ('', Bug.CloseReason.FIXED):
            return 'Choose why this bug is closed without a fix.'
        else:
            close_reason = reason
        if close_reason not in Bug.CloseReason.values:
            return 'Choose a valid reason.'
    extra = {}
    if target == S.FIXED:           # stamp the developers who hold the project roles right now
        backend, frontend = solved_names(bug.project, bug.layer, fallback=user)
        extra = {'solved_by_backend': backend, 'solved_by_frontend': frontend}
    if close_reason == Bug.CloseReason.NOT_REQUIRED:
        if not bug.project.ba:
            return 'Assign a business analyst to this project (Team tab) before marking a bug as not required.'
        extra = {'ba_name': bug.project.ba.display_name}
    now = timezone.now()
    with transaction.atomic():
        # The filter on status makes this safe if two people click at the same moment.
        changed = Bug.objects.filter(pk=bug.pk, status=bug.status).update(
            status=target, close_reason=close_reason, updated_at=now,
            closed_at=now if target == S.CLOSED else None,
            reopen_count=F('reopen_count') + (1 if target == S.REOPENED else 0), **extra)
        if not changed:
            return 'Someone changed this bug while you were looking at it. Review the new status and try again.'
        shown = Bug.Status(target).label + (f' ({Bug.CloseReason(close_reason).label})' if close_reason else '')
        log(bug, user, 'status', Bug.Status(bug.status).label, shown)
    bug.refresh_from_db()
    return None
