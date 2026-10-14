"""Project team rules: who a bug goes to, whose name is recorded when it is fixed."""
OPEN_STATES = ('open', 'in_progress', 'reopened')   # bugs nobody has fixed yet


def _pk(user):
    return user.pk if user else None


def defaults_for(team, layer):
    """team is {'backend': user|None, 'frontend': user|None}. Returns (primary, co_assignee)."""
    backend, frontend = team.get('backend'), team.get('frontend')
    if layer == 'backend':
        primary, co = backend, None
    elif layer == 'frontend':
        primary, co = frontend, None
    else:                                   # Frontend & Backend: both developers are involved
        primary, co = (backend or frontend), (frontend if backend else None)
    if co and primary and co.pk == primary.pk:
        co = None
    return primary, co


def default_assignees(project, layer):
    return defaults_for({'backend': project.backend_dev, 'frontend': project.frontend_dev}, layer)


def solved_names(project, layer, fallback=None):
    """Names to stamp on a bug when it is marked Fixed: the project's developers for that layer, right now."""
    backend = project.backend_dev.display_name if project.backend_dev else ''
    frontend = project.frontend_dev.display_name if project.frontend_dev else ''
    if layer == 'backend':
        frontend = ''
    elif layer == 'frontend':
        backend = ''
    if not backend and not frontend and fallback is not None and fallback.role == 'developer':
        if layer == 'frontend':
            frontend = fallback.display_name
        else:
            backend = fallback.display_name
    return backend, frontend


def apply_team_change(project, old, new, user):
    """When the team changes, bugs nobody has fixed yet follow the new developers.
    Fixed and closed bugs are untouched, so they keep the name of whoever solved them."""
    from .workflow import log
    moved = 0
    for bug in project.bugs.filter(status__in=OPEN_STATES).select_related('assignee', 'co_assignee'):
        old_primary, old_co = defaults_for(old, bug.layer)
        new_primary, new_co = defaults_for(new, bug.layer)
        changed = False
        if bug.assignee_id == _pk(old_primary) and _pk(old_primary) != _pk(new_primary):
            log(bug, user, 'assignee', bug.assignee.display_name if bug.assignee else '',
                new_primary.display_name if new_primary else '')
            bug.assignee, changed = new_primary, True
        if bug.co_assignee_id == _pk(old_co) and _pk(old_co) != _pk(new_co):
            log(bug, user, 'co-assignee', bug.co_assignee.display_name if bug.co_assignee else '',
                new_co.display_name if new_co else '')
            bug.co_assignee, changed = new_co, True
        if changed:
            bug.save(update_fields=['assignee', 'co_assignee', 'updated_at'])
            moved += 1
    return moved
