from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.utils import csv_download, safe_next
from projects.access import project_for
from projects.models import SubModule
from .forms import TestCaseForm
from . import importer
from .models import ImportBatch, TestCase
from .services import archive_cases, clean_row, create_case, delete_case

from accounts.roles import CASE_EDITORS
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
GRID_FIELDS = ['module', 'sub_module', 'title', 'steps', 'expected_result', 'layer', 'priority']


def filtered_cases(request, project):
    """One place that turns the filter boxes (?q=...&module=...) into a database query.
    The list page and the CSV export both use it, so they always agree."""
    g = request.GET
    qs = project.test_cases.select_related('module', 'sub_module', 'created_by')
    qs = qs.filter(archived=(g.get('archived') == '1'))
    q = g.get('q', '').strip()
    if q:
        cond = Q(title__icontains=q) | Q(steps__icontains=q) | Q(expected_result__icontains=q)
        digits = q.upper().removeprefix('TC-')
        if digits.isdigit():
            cond |= Q(number=int(digits))
        qs = qs.filter(cond)
    if g.get('module', '').isdigit():
        qs = qs.filter(module_id=g['module'])
    if g.get('sub_module', '').isdigit():
        qs = qs.filter(sub_module_id=g['sub_module'])
    if g.get('layer') in TestCase.Layer.values:
        qs = qs.filter(layer=g['layer'])
    if g.get('priority') in TestCase.Priority.values:
        qs = qs.filter(priority=g['priority'])
    return qs


@login_required
def case_list(request, project_id):
    project = project_for(request.user, project_id)
    page = Paginator(filtered_cases(request, project), 25).get_page(request.GET.get('page'))
    params = request.GET.copy(); params.pop('page', None)
    return render(request, 'testcases/list.html', {
        'project': project, 'page': page, 'querystring': params.urlencode(),
        'modules': project.modules.filter(archived=False),
        'submodules': SubModule.objects.filter(module__project=project, archived=False),
        'layers': TestCase.Layer.choices, 'priorities': TestCase.Priority.choices,
        'can_edit': request.user.role in CASE_EDITORS,
    })


def _submodule_map(project):
    """{module_id: [[sub_id, name], ...]} so the page can filter the sub-module dropdown."""
    data = {}
    for s in SubModule.objects.filter(module__project=project, archived=False):
        data.setdefault(s.module_id, []).append([s.id, s.name])
    return data


@login_required
@role_required(*CASE_EDITORS)
def case_create(request, project_id):
    project = project_for(request.user, project_id)
    form = TestCaseForm(request.POST or None, project=project)
    if form.is_valid():
        case = form.save(commit=False)
        case.project, case.created_by = project, request.user
        case.save()
        messages.success(request, f'{case.code} created.')
        return redirect('case_list', project_id=project.pk)
    return render(request, 'testcases/form.html', {'project': project, 'form': form,
                  'title': 'New test case', 'submodule_map': _submodule_map(project)})


@login_required
@role_required(*CASE_EDITORS)
def case_edit(request, project_id, pk):
    project = project_for(request.user, project_id)
    case = get_object_or_404(project.test_cases, pk=pk)
    form = TestCaseForm(request.POST or None, instance=case, project=project)
    if form.is_valid():
        form.save()
        messages.success(request, f'{case.code} saved.')
        return redirect('case_list', project_id=project.pk)
    return render(request, 'testcases/form.html', {'project': project, 'form': form,
                  'title': f'Edit {case.code}', 'submodule_map': _submodule_map(project)})


@login_required
@role_required(*CASE_EDITORS)
def case_delete(request, project_id, pk):
    project = project_for(request.user, project_id)
    case = get_object_or_404(project.test_cases, pk=pk)
    blocked = case.results.exclude(result='not_run').exists()
    if request.method == 'POST':
        if delete_case(case):
            messages.success(request, f'{case.code} deleted.')
            return redirect('case_list', project_id=project.pk)
        messages.error(request, f'{case.code} has results in test runs and cannot be deleted. Archive it instead.')
        return redirect('case_list', project_id=project.pk)
    return render(request, 'testcases/case_confirm_delete.html', {'project': project, 'case': case, 'blocked': blocked})


@login_required
@role_required(*CASE_EDITORS)
@require_POST
def case_clone(request, project_id, pk):
    project = project_for(request.user, project_id)
    case = get_object_or_404(project.test_cases, pk=pk)
    case.pk, case.number, case.archived = None, None, False   # a new row; save() assigns the next number
    case.title, case.created_by = f'Copy of {case.title}'[:300], request.user
    case.save()
    messages.success(request, f'Cloned. Edit {case.code} below.')
    return redirect('case_edit', project_id=project.pk, pk=case.pk)


@login_required
@role_required(*CASE_EDITORS)
@require_POST
def bulk_action(request, project_id):
    project = project_for(request.user, project_id)
    cases = project.test_cases.filter(pk__in=request.POST.getlist('ids'))
    action = request.POST.get('action', '')
    if action == 'delete' and cases:
        chosen = list(cases)
        deleted = sum(1 for c in chosen if delete_case(c))
        messages.success(request, f'Deleted {deleted} test case(s).')
        if deleted < len(chosen):
            messages.warning(request, f'{len(chosen) - deleted} could not be deleted because they have results in test runs. Archive them instead.')
        return redirect(safe_next(request, 'case_list', project.pk))
    if action == 'archive' and cases:
        chosen = list(cases)
        archive_cases(chosen)
        messages.success(request, f'Archived {len(chosen)} test case(s).')
        return redirect(safe_next(request, 'case_list', project.pk))
    updates = {'restore': {'archived': False}}
    for value in TestCase.Priority.values:
        updates[f'priority:{value}'] = {'priority': value}
    for value in TestCase.Layer.values:
        updates[f'layer:{value}'] = {'layer': value}
    if action in updates and cases:
        count = cases.update(**updates[action])
        messages.success(request, f'Updated {count} test case(s).')
    else:
        messages.error(request, 'Select at least one test case and an action.')
    return redirect(safe_next(request, 'case_list', project.pk))


@login_required
@role_required(*CASE_EDITORS)
def quick_add(request, project_id):
    project = project_for(request.user, project_id)
    rows, errors = [], {}
    if request.method == 'POST':
        columns = [request.POST.getlist(f) for f in GRID_FIELDS]
        for values in zip(*columns):
            row = dict(zip(GRID_FIELDS, values))
            if any(row[f].strip() for f in ('module', 'title', 'steps', 'expected_result')):
                rows.append(row)          # fully blank rows are skipped
        cleaned = []
        for i, row in enumerate(rows):
            data, errs = clean_row(row)
            cleaned.append(data)
            if errs:
                errors[i] = errs
        if not rows:
            messages.error(request, 'Fill in at least one row.')
        elif not errors:
            with transaction.atomic():    # all rows are saved, or none
                for data in cleaned:
                    create_case(project, request.user, data)
            messages.success(request, f'{len(cleaned)} test case(s) added.')
            return redirect('case_list', project_id=project.pk)
    if not rows:
        rows = [{} for _ in range(5)]
    return render(request, 'testcases/quick_add.html', {
        'project': project, 'rows': [dict(r, errs=errors.get(i)) for i, r in enumerate(rows)],
        'modules': project.modules.filter(archived=False),
        'submodules': SubModule.objects.filter(module__project=project, archived=False),
        'layers': TestCase.Layer.choices, 'priorities': TestCase.Priority.choices})


@login_required
def export_csv(request, project_id):
    project = project_for(request.user, project_id)
    header = ['MODULE', 'SUB-MODULE', 'TEST CASE', 'STEPS TO REPRODUCE', 'EXPECTED RESULT', 'ACTUAL RESULT',
              'BACKEND/FRONTEND', 'DATE', 'QA NAME']
    rows = ([c.module.name, c.sub_module.name if c.sub_module else '', c.title, c.steps, c.expected_result, '',
             c.get_layer_display(), c.created_at.strftime('%Y-%m-%d'), c.created_by.display_name if c.created_by else '']
            for c in filtered_cases(request, project))
    return csv_download(f'testcases-{slugify(project.name)}-{date.today():%Y%m%d}.csv', header, rows)

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _xlsx_response(content, filename):
    response = HttpResponse(content, content_type=XLSX)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@role_required(*CASE_EDITORS)
def import_home(request, project_id):
    project = project_for(request.user, project_id)
    if request.method == 'POST':
        upload = request.FILES.get('file')
        if not upload:
            messages.error(request, 'Choose an .xlsx file first.')
        elif not upload.name.lower().endswith('.xlsx'):
            messages.error(request, 'Only .xlsx files are accepted. Download the template to start.')
        elif upload.size > MAX_UPLOAD_BYTES:
            messages.error(request, 'The file is larger than 5 MB.')
        else:
            try:
                rows = importer.parse_upload(upload, project)
            except importer.ImportFileError as exc:
                messages.error(request, str(exc))
            else:
                project.import_batches.filter(user=request.user, status='preview').delete()  # drop old unconfirmed uploads
                batch = ImportBatch.objects.create(project=project, user=request.user,
                                                   filename=upload.name[:255], rows=rows)
                return redirect('import_detail', project_id=project.pk, pk=batch.pk)
    history = project.import_batches.filter(status='done').select_related('user')[:20]
    return render(request, 'testcases/import_home.html', {'project': project, 'history': history})


def _batch_for(request, project, pk):
    batch = get_object_or_404(project.import_batches, pk=pk)
    if batch.status == 'preview' and batch.user_id != request.user.id:
        raise Http404          # an unconfirmed upload belongs to the person who made it
    return batch


@login_required
@role_required(*CASE_EDITORS)
def import_detail(request, project_id, pk):
    project = project_for(request.user, project_id)
    batch = _batch_for(request, project, pk)
    order = {'invalid': 0, 'duplicate': 1, 'new': 2}
    rows = sorted(batch.rows, key=lambda r: (order[r['status']], r['n']))
    return render(request, 'testcases/import_detail.html', {
        'project': project, 'batch': batch, 'rows': rows[:300], 'hidden': max(0, len(rows) - 300),
        'n_new': batch.count('new'), 'n_dup': batch.count('duplicate'), 'n_bad': batch.count('invalid')})


@login_required
@role_required(*CASE_EDITORS)
@require_POST
def import_confirm(request, project_id, pk):
    project = project_for(request.user, project_id)
    batch = _batch_for(request, project, pk)
    policy = 'update' if request.POST.get('policy') == 'update' else 'skip'
    with transaction.atomic():
        # Only one request can flip preview -> done, so a double click cannot import twice.
        claimed = ImportBatch.objects.filter(pk=batch.pk, status='preview').update(status='importing')
        if not claimed:
            messages.error(request, 'This upload was already imported.')
            return redirect('import_detail', project_id=project.pk, pk=batch.pk)
        batch.refresh_from_db()
        importer.apply_batch(batch, request.user, policy)
    messages.success(request, f'Import finished: {batch.created_count} added, {batch.updated_count} updated.')
    return redirect('import_detail', project_id=project.pk, pk=batch.pk)


@login_required
@role_required(*CASE_EDITORS)
@require_POST
def import_cancel(request, project_id, pk):
    project = project_for(request.user, project_id)
    batch = _batch_for(request, project, pk)
    if batch.status == 'preview':
        batch.delete()
    return redirect('import_home', project_id=project.pk)


@login_required
@role_required(*CASE_EDITORS)
def import_template(request, project_id):
    project_for(request.user, project_id)
    return _xlsx_response(importer.build_template(), 'test-case-template.xlsx')


@login_required
@role_required(*CASE_EDITORS)
def import_errors(request, project_id, pk):
    project = project_for(request.user, project_id)
    batch = _batch_for(request, project, pk)
    return _xlsx_response(importer.build_error_report(batch), f'rejected-rows-{batch.pk}.xlsx')
