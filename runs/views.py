from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from datetime import date

from django.utils.text import slugify

from accounts.decorators import role_required
from accounts.utils import csv_download
from accounts.roles import CASE_EDITORS, EDITORS, LEADS
from bugs.models import Bug
from bugs.services import create_bug_from_result
from projects.access import project_for
from .forms import RunForm
from .models import TestResult, TestRun


def _ordered_ids(run):
    return list(run.results.ordered().values_list('pk', flat=True))


def first_pending(run):
    """Where 'Start / Continue' goes: the first case not run yet, otherwise the first skipped one."""
    rows = list(run.results.ordered().values_list('pk', 'result'))
    return next((pk for pk, r in rows if r == 'not_run'), None) or next((pk for pk, r in rows if r == 'skip'), None)


def next_pending(run, current):
    """The case to show after `current`: cases not run yet come first; skipped cases (which sit at the end
    of the run) come back once nothing else is waiting. None when there is nothing left."""
    ids = _ordered_ids(run)
    state = dict(run.results.values_list('pk', 'result'))
    i = ids.index(current.pk)
    others = ids[i + 1:] + ids[:i]                     # everything except `current`, starting after it
    for wanted in ('not_run', 'skip'):
        found = next((pk for pk in others if state[pk] == wanted), None)
        if found:
            return found
    return None


def _with_linked_bugs(project, results):
    """Attach `.linked`: bugs raised from this result, plus open bugs already tracking the same test case."""
    open_by_case = {}
    for bug in Bug.objects.filter(project=project, test_case_id__in=[r.test_case_id for r in results]).exclude(status='closed'):
        open_by_case.setdefault(bug.test_case_id, []).append(bug)
    for r in results:
        merged = {b.pk: b for b in r.bugs.all()}
        for bug in open_by_case.get(r.test_case_id, []):
            merged.setdefault(bug.pk, bug)
        r.linked = list(merged.values())
    return results


def after_result(request, project, run, result):
    """Where to go after a result is saved: the next case waiting, or back to the run."""
    nxt = next_pending(run, result)
    if nxt:
        return redirect('run_execute', project_id=project.pk, pk=run.pk, rid=nxt)
    messages.success(request, 'Every case in this run now has a result.')
    return redirect('run_detail', project_id=project.pk, pk=run.pk)


@login_required
def run_list(request, project_id):
    project = project_for(request.user, project_id)
    runs = [(r, r.summary()) for r in project.runs.select_related('created_by', 'assigned_qa')]
    return render(request, 'runs/run_list.html', {'project': project, 'runs': runs,
                                                  'can_edit': request.user.role in CASE_EDITORS})


@login_required
@role_required(*CASE_EDITORS)
def run_create(request, project_id):
    project = project_for(request.user, project_id)
    form = RunForm(request.POST or None, project=project, user=request.user)
    if form.is_valid():
        d = form.cleaned_data
        run = TestRun.objects.create(project=project, name=d['name'], run_date=d['run_date'], build=d['build'],
                                     environment=d['environment'], assigned_qa=d['assigned_qa'], created_by=request.user)
        count = run.sync_cases()                       # every active test case goes into the run
        messages.success(request, f'Run created with all {count} active test cases.')
        return redirect('run_detail', project_id=project.pk, pk=run.pk)
    return render(request, 'runs/run_form.html', {'project': project, 'form': form,
                  'case_count': project.test_cases.filter(archived=False).count()})


@login_required
def run_detail(request, project_id, pk):
    project = project_for(request.user, project_id)
    run = get_object_or_404(project.runs, pk=pk)
    if run.status == 'open':
        run.sync_cases()                               # cases added since the run was created appear here
    results = run.results.ordered().select_related('test_case__module', 'test_case__sub_module').prefetch_related('bugs')
    chosen = request.GET.get('result', '')
    if chosen in TestResult.Result.values:
        results = results.filter(result=chosen)
    results = _with_linked_bugs(project, list(results))
    summary = run.summary()
    return render(request, 'runs/run_detail.html', {
        'project': project, 'run': run, 'results': results, 'summary': summary, 'chosen': chosen,
        'first_pending': first_pending(run), 'only_skipped': summary['not_run'] == 0 and summary['skip'] > 0,
        'choices': TestResult.Result.choices,
        'can_edit': request.user.role in EDITORS, 'can_reopen': request.user.role in LEADS})


@login_required
def run_execute(request, project_id, pk, rid):
    project = project_for(request.user, project_id)
    run = get_object_or_404(project.runs, pk=pk)
    if run.status == 'open':
        run.sync_cases()
    result = get_object_or_404(run.results.select_related('test_case__module', 'test_case__sub_module'), pk=rid)
    ids = _ordered_ids(run)
    i = ids.index(result.pk)
    return render(request, 'runs/execute.html', {
        'project': project, 'run': run, 'result': result, 'case': result.test_case, 'summary': run.summary(),
        'prev_id': ids[i - 1] if i else None, 'next_id': ids[i + 1] if i + 1 < len(ids) else None,
        'position': i + 1, 'total': len(ids), 'bugs': _with_linked_bugs(project, [result])[0].linked,
        'can_edit': request.user.role in EDITORS and run.status == 'open'})


@login_required
@role_required(*EDITORS)
@require_POST
def run_set_result(request, project_id, pk, rid):
    project = project_for(request.user, project_id)
    run = get_object_or_404(project.runs, pk=pk)
    result = get_object_or_404(run.results, pk=rid)
    value = request.POST.get('result', '')
    if run.status != 'open':
        messages.error(request, 'This run is closed. A manager can reopen it.')
        return redirect('run_detail', project_id=project.pk, pk=run.pk)
    if value not in TestResult.Result.values or value == 'not_run':
        messages.error(request, 'Choose Pass, Fail, Blocked or Skip.')
        return redirect('run_execute', project_id=project.pk, pk=run.pk, rid=result.pk)
    result.result, result.note = value, request.POST.get('note', '').strip()
    result.tester, result.executed_at = request.user, timezone.now()
    result.save()
    if value == 'fail':     # a failed case becomes a bug in the Bugs tab, no form needed
        bug, outcome = create_bug_from_result(result, request.user)
        if outcome == 'created':
            who = ' and '.join(u.display_name for u in (bug.assignee, bug.co_assignee) if u)
            messages.success(request, f'{bug.code} created' + (f' and assigned to {who}.' if who else '.'))
            if not who:
                messages.warning(request, 'No developer is assigned for this layer yet. Set one in the Team tab.')
        elif outcome == 'noted':
            messages.warning(request, f'{bug.code} already tracks this test case, so a note was added instead of a new bug.')
    return after_result(request, project, run, result)


@login_required
@role_required(*EDITORS)
@require_POST
def run_close(request, project_id, pk):
    project = project_for(request.user, project_id)
    run = get_object_or_404(project.runs, pk=pk)
    left = run.results.filter(result__in=['not_run', 'skip']).count()
    run.status, run.closed_at = 'closed', timezone.now()
    run.save()
    messages.success(request, 'Run closed.' + (f' {left} case(s) were left without a result.' if left else ''))
    return redirect('run_detail', project_id=project.pk, pk=run.pk)


@login_required
@role_required(*LEADS)
@require_POST
def run_reopen(request, project_id, pk):
    project = project_for(request.user, project_id)
    run = get_object_or_404(project.runs, pk=pk)
    run.status, run.closed_at = 'open', None
    run.save()
    messages.success(request, 'Run reopened.')
    return redirect('run_detail', project_id=project.pk, pk=run.pk)


@login_required
def run_export(request, project_id, pk):
    """Every test case in the run with its result. Same first nine columns as the other exports,
    then the result details. Skipped cases are at the end, exactly like on screen."""
    project = project_for(request.user, project_id)
    run = get_object_or_404(project.runs, pk=pk)
    results = run.results.ordered().select_related('test_case__module', 'test_case__sub_module', 'tester').prefetch_related('bugs')
    chosen = request.GET.get('result', '')
    if chosen in TestResult.Result.values:
        results = results.filter(result=chosen)
    results = _with_linked_bugs(project, list(results))
    header = ['MODULE', 'SUB-MODULE', 'TEST CASE', 'STEPS TO REPRODUCE', 'EXPECTED RESULT', 'ACTUAL RESULT',
              'BACKEND/FRONTEND', 'DATE', 'QA NAME', 'TEST ID', 'RESULT', 'BUG', 'RUN', 'VERSION', 'RUN DATE']
    rows = ([c.module.name, c.sub_module.name if c.sub_module else '', c.title, c.steps, c.expected_result, r.note,
             c.get_layer_display(), r.executed_at.strftime('%Y-%m-%d') if r.executed_at else '',
             r.tester.display_name if r.tester else '', c.code, r.get_result_display(),
             '; '.join(b.code for b in r.linked), run.name, run.build, run.run_date.isoformat()]
            for r in results for c in [r.test_case])
    return csv_download(f'run-{slugify(run.name)}-{date.today():%Y%m%d}.csv', header, rows)


@login_required
def run_list_export(request, project_id):
    project = project_for(request.user, project_id)
    header = ['RUN', 'DATE', 'VERSION', 'QA', 'ENVIRONMENT', 'STATUS', 'TOTAL', 'PASS', 'FAIL', 'BLOCKED',
              'SKIPPED', 'NOT RUN', 'EXECUTED %']
    def rows():
        for r in project.runs.select_related('assigned_qa').order_by('run_date', 'id'):
            s = r.summary()
            yield [r.name, r.run_date.isoformat(), r.build, r.assigned_qa.display_name if r.assigned_qa else '',
                   r.environment, r.get_status_display(), s['total'], s['pass'], s['fail'], s['blocked'], s['skip'],
                   s['not_run'], s['percent']]
    return csv_download(f'runs-{slugify(project.name)}-{date.today():%Y%m%d}.csv', header, rows())
