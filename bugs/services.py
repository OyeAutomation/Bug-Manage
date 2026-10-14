from .models import Bug, BugComment
from .team import default_assignees
from .workflow import log


def create_bug_from_result(result, user):
    """A failed test case becomes a bug automatically. Returns (bug, outcome).
    outcome: 'created' | 'noted' (an open bug already tracks this case) | 'exists' (this result already has one)."""
    run, case, project = result.run, result.test_case, result.run.project
    existing = result.bugs.first()
    if existing:
        return existing, 'exists'
    open_bug = project.bugs.filter(test_case=case).exclude(status='closed').first()
    if open_bug:                       # do not create a duplicate; leave a note on the existing bug instead
        text = f'Failed again in run "{run.name}"' + (f' (build {run.build})' if run.build else '') + '.'
        if result.note:
            text += f'\nActual result: {result.note}'
        BugComment.objects.create(bug=open_bug, author=user, text=text)
        return open_bug, 'noted'
    primary, co = default_assignees(project, case.layer)
    bug = Bug.objects.create(
        project=project, title=case.title[:300], module=case.module, sub_module=case.sub_module,
        test_case=case, run=run, result=result, steps=case.steps, expected_result=case.expected_result,
        actual_result=result.note, layer=case.layer, priority=case.priority, environment=run.environment,
        build=run.build, assignee=primary, co_assignee=co, reporter=user)
    log(bug, user, 'created', '', 'from a failed test case')
    return bug, 'created'
