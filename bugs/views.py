from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from datetime import date

from django.utils.text import slugify

from accounts.decorators import role_required
from accounts.utils import csv_download
from accounts.roles import EDITORS
from projects.access import project_for
from projects.models import SubModule
from runs.models import TestResult
from runs.views import after_result
from .forms import BugForm
from .models import Bug, BugComment
from .team import OPEN_STATES, default_assignees
from .workflow import FIXED_STATES, ORDER, allowed_targets, change_status, log

TRACKED = ['title', 'module', 'sub_module', 'steps', 'expected_result', 'actual_result', 'layer', 'severity',
           'priority', 'environment', 'build', 'assignee', 'release_phase']


def _snapshot(bug):
    """Readable value of every tracked field, so we can log exactly what an edit changed."""
    out = {}
    for name in TRACKED:
        field = bug._meta.get_field(name)
        value = getattr(bug, name)
        if field.choices:
            value = getattr(bug, f'get_{name}_display')()
        elif field.is_relation:
            value = getattr(value, 'display_name', None) or str(value or '')
        out[name] = str(value or '')
    return out


def _fixed_by(bug):
    """'Rohan M. (Backend), Meera S. (Frontend)' once the bug has been fixed; empty before that."""
    solved = bug.status in FIXED_STATES or (bug.status == 'closed' and bug.close_reason == 'fixed')
    if not solved:
        return ''
    parts = [f'{n} ({label})' for n, label in ((bug.solved_by_backend, 'Backend'), (bug.solved_by_frontend, 'Frontend')) if n]
    return ', '.join(parts)


def filtered_bugs(request, project, default_status='active'):
    """The Bugs tab filters (?status=...&layer=...) turned into a query. The list and the CSV export share it,
    so a download always matches what is on screen."""
    g = request.GET
    qs = project.bugs.select_related('module', 'sub_module', 'assignee', 'co_assignee', 'reporter', 'test_case', 'run')
    status = g.get('status', default_status)
    if status == 'active':
        qs = qs.exclude(status='closed')
    elif status in Bug.Status.values:
        qs = qs.filter(status=status)
    q = g.get('q', '').strip()
    if q:
        cond = Q(title__icontains=q) | Q(actual_result__icontains=q)
        digits = q.upper().removeprefix('BUG-')
        if digits.isdigit():
            cond |= Q(number=int(digits))
        qs = qs.filter(cond)
    for key in ('severity', 'priority', 'layer'):
        if g.get(key) in dict(Bug._meta.get_field(key).choices):
            qs = qs.filter(**{key: g[key]})
    if g.get('module', '').isdigit():
        qs = qs.filter(module_id=g['module'])
    if g.get('assignee') == 'me':
        qs = qs.filter(Q(assignee=request.user) | Q(co_assignee=request.user))
    elif g.get('assignee', '').isdigit():
        qs = qs.filter(assignee_id=g['assignee'])
    return qs, status


@login_required
def bug_list(request, project_id):
    project = project_for(request.user, project_id)
    qs, status = filtered_bugs(request, project)
    page = Paginator(qs, 25).get_page(request.GET.get('page'))
    params = request.GET.copy(); params.pop('page', None)
    return render(request, 'bugs/bug_list.html', {
        'project': project, 'page': page, 'querystring': params.urlencode(), 'status': status,
        'modules': project.modules.filter(archived=False), 'members': project.members.filter(is_active=True),
        'statuses': Bug.Status.choices, 'severities': Bug.Severity.choices, 'layers': Bug.Layer.choices,
        'can_edit': request.user.role in EDITORS})


@login_required
def bug_export(request, project_id):
    """CSV of the bugs matching the current filters. The first nine columns are the agreed format;
    ?detail=1 adds more columns after them."""
    project = project_for(request.user, project_id)
    qs, _ = filtered_bugs(request, project, default_status='all')       # a bare download link means every bug
    header = ['MODULE', 'SUB-MODULE', 'TEST CASE', 'STEPS TO REPRODUCE', 'EXPECTED RESULT', 'ACTUAL RESULT',
              'BACKEND/FRONTEND', 'DATE', 'QA NAME']
    detail = request.GET.get('detail') == '1'
    if detail:
        header += ['BUG ID', 'BUG TITLE', 'STATUS', 'CLOSE REASON', 'SEVERITY', 'PRIORITY', 'ASSIGNEE',
                   'SECOND DEVELOPER', 'FIXED BY', 'ENVIRONMENT', 'VERSION', 'TEST CASE ID', 'RUN', 'TIMES REOPENED', 'CLOSED DATE']

    def rows():
        for b in qs.order_by('number'):
            row = [b.module.name, b.sub_module.name if b.sub_module else '', b.test_case.title if b.test_case else b.title,
                   b.steps, b.expected_result, b.actual_result, b.get_layer_display(), b.created_at.strftime('%Y-%m-%d'),
                   b.reporter.display_name if b.reporter else '']
            if detail:
                row += [b.code, b.title, b.get_status_display(), b.get_close_reason_display() if b.close_reason else '',
                        b.get_severity_display(), b.get_priority_display(), b.assignee.display_name if b.assignee else '',
                        b.co_assignee.display_name if b.co_assignee else '', _fixed_by(b), b.environment, b.build,
                        b.test_case.code if b.test_case else '', b.run.name if b.run else '', b.reopen_count,
                        b.closed_at.strftime('%Y-%m-%d') if b.closed_at else '']
            yield row
    return csv_download(f'bugs-{slugify(project.name)}-{date.today():%Y%m%d}.csv', header, rows())


def _submodule_map(project):
    data = {}
    for s in SubModule.objects.filter(module__project=project, archived=False):
        data.setdefault(s.module_id, []).append([s.id, s.name])
    return data


@login_required
@role_required(*EDITORS)
def bug_create(request, project_id):
    project = project_for(request.user, project_id)
    result = None
    rid = request.POST.get('result') or request.GET.get('result')
    if rid and rid.isdigit():
        result = get_object_or_404(TestResult.objects.select_related('run', 'test_case__module', 'test_case__sub_module'),
                                   pk=rid, run__project=project)
    initial, similar = {}, []
    if result:
        case, run = result.test_case, result.run
        initial = {'title': case.title, 'module': case.module, 'sub_module': case.sub_module, 'steps': case.steps,
                   'expected_result': case.expected_result, 'layer': case.layer, 'priority': case.priority,
                   'environment': run.environment, 'build': run.build, 'actual_result': result.note}
        similar = project.bugs.exclude(status='closed').filter(test_case=case)   # warn about likely duplicates
    form = BugForm(request.POST or None, project=project, initial=initial)
    if form.is_valid():
        bug = form.save(commit=False)
        bug.project, bug.reporter = project, request.user
        if result:
            bug.test_case, bug.run, bug.result = result.test_case, result.run, result
        bug.save()
        log(bug, request.user, 'created')
        messages.success(request, f'{bug.code} raised.')
        if result and result.run.status == 'open':
            return after_result(request, project, result.run, result)   # keep testing: jump to the next case
        return redirect('bug_detail', project_id=project.pk, pk=bug.pk)
    return render(request, 'bugs/bug_form.html', {
        'project': project, 'form': form, 'title': 'Raise a bug', 'result': result, 'similar': similar,
        'submodule_map': _submodule_map(project)})


@login_required
def bug_detail(request, project_id, pk):
    project = project_for(request.user, project_id)
    bug = get_object_or_404(project.bugs.select_related('module', 'sub_module', 'test_case', 'run', 'assignee', 'reporter'), pk=pk)
    return render(request, 'bugs/bug_detail.html', {
        'project': project, 'bug': bug, 'targets': allowed_targets(bug.status, request.user.role),
        'closes_without_fix': bug.status not in FIXED_STATES,
        'reasons': [(v, l) for v, l in Bug.CloseReason.choices if v != 'fixed'],
        'members': project.members.filter(is_active=True), 'history': bug.history.select_related('user'),
        'steps': [s for s in bug.steps.splitlines() if s.strip()],
        'ordered': [(s.value, s.label) for s in ORDER],
        'fixed_by': _fixed_by(bug), 'layers': Bug.Layer.choices, 'can_edit': request.user.role in EDITORS})


@login_required
@role_required(*EDITORS)
def bug_edit(request, project_id, pk):
    project = project_for(request.user, project_id)
    bug = get_object_or_404(project.bugs, pk=pk)
    version = bug.updated_at.isoformat()          # remember which version of the bug this form started from
    before = _snapshot(bug)
    form = BugForm(request.POST or None, instance=bug, project=project)
    if request.method == 'POST' and request.POST.get('version') != version:
        messages.error(request, 'Someone else changed this bug after you opened it. Your edit was not saved. '
                                'Review the latest version and try again.')
        return redirect('bug_detail', project_id=project.pk, pk=bug.pk)
    if form.is_valid():
        form.save()
        after = _snapshot(bug)
        for name in TRACKED:
            if before[name] != after[name]:
                log(bug, request.user, name, before[name], after[name])
        if before['layer'] != after['layer'] and before['assignee'] == after['assignee']:
            # The layer changed and nobody picked a person: hand it to the project's developers for the new layer.
            primary, co = default_assignees(project, bug.layer)
            log(bug, request.user, 'assignee', before['assignee'], primary.display_name if primary else '')
            bug.assignee, bug.co_assignee = primary, co
            bug.save(update_fields=['assignee', 'co_assignee', 'updated_at'])
        messages.success(request, f'{bug.code} saved.')
        return redirect('bug_detail', project_id=project.pk, pk=bug.pk)
    return render(request, 'bugs/bug_form.html', {'project': project, 'form': form, 'title': f'Edit {bug.code}',
                  'bug': bug, 'version': version, 'similar': [], 'submodule_map': _submodule_map(project)})


@login_required
@require_POST
def bug_status(request, project_id, pk):
    project = project_for(request.user, project_id)
    bug = get_object_or_404(project.bugs, pk=pk)
    target, reason = request.POST.get('target', ''), request.POST.get('reason', '')
    if request.POST.get('quick') == 'not_required':      # the one-click 'Not required (BA)' button
        target, reason = 'closed', 'not_required'
    error = change_status(bug, request.user, target, reason, seen_status=request.POST.get('seen_status'))
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f'{bug.code} is now {bug.get_status_display()}.')
    return redirect('bug_detail', project_id=project.pk, pk=bug.pk)


@login_required
@require_POST
def bug_assign(request, project_id, pk):
    project = project_for(request.user, project_id)
    bug = get_object_or_404(project.bugs, pk=pk)
    members = project.members
    for field, label in (('assignee', 'assignee'), ('co_assignee', 'co-assignee')):
        who = members.filter(pk=request.POST.get(field) or 0).first()
        old = getattr(bug, field)
        if (old.pk if old else None) != (who.pk if who else None):
            log(bug, request.user, label, old.display_name if old else '', who.display_name if who else '')
            setattr(bug, field, who)
    bug.save(update_fields=['assignee', 'co_assignee', 'updated_at'])
    messages.success(request, 'Assignment updated.')
    return redirect('bug_detail', project_id=project.pk, pk=bug.pk)


@login_required
@require_POST
def bug_comment(request, project_id, pk):
    project = project_for(request.user, project_id)
    bug = get_object_or_404(project.bugs, pk=pk)
    text = request.POST.get('text', '').strip()
    if text:
        BugComment.objects.create(bug=bug, author=request.user, text=text)
    else:
        messages.error(request, 'Write a comment first.')
    return redirect('bug_detail', project_id=project.pk, pk=bug.pk)


@login_required
@require_POST
def bug_layer(request, project_id, pk):
    """Any project member (developer, BA, tester, manager) can correct a bug's developer type."""
    project = project_for(request.user, project_id)
    bug = get_object_or_404(project.bugs, pk=pk)
    new = request.POST.get('layer', '')
    if new not in Bug.Layer.values:
        messages.error(request, 'Choose Backend, Frontend or Frontend & Backend.')
    elif new != bug.layer:
        old_label, old_layer = bug.get_layer_display(), bug.layer
        old_primary, old_co = default_assignees(project, old_layer)
        bug.layer = new
        fields = ['layer', 'updated_at']
        log(bug, request.user, 'layer', old_label, Bug.Layer(new).label)
        pk_of = lambda u: u.pk if u else None
        # Bugs nobody has fixed yet follow the new type, but only if the people on them were chosen automatically.
        if bug.status in OPEN_STATES and bug.assignee_id == pk_of(old_primary) and bug.co_assignee_id == pk_of(old_co):
            primary, co = default_assignees(project, new)
            if (pk_of(primary), pk_of(co)) != (bug.assignee_id, bug.co_assignee_id):
                log(bug, request.user, 'assignee', old_primary.display_name if old_primary else '', primary.display_name if primary else '')
                bug.assignee, bug.co_assignee = primary, co
                fields += ['assignee', 'co_assignee']
        bug.save(update_fields=fields)       # names already stamped on a fixed bug are never touched
        messages.success(request, f'Developer type changed to {bug.get_layer_display()}.')
    return redirect('bug_detail', project_id=project.pk, pk=bug.pk)
