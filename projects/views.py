from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.roles import CASE_EDITORS
from .access import project_for
from .forms import ModuleForm, ProjectForm, SubModuleForm, TeamForm
from .models import Module, Project, TeamChange


_project_for = project_for


@login_required
def dashboard(request):
    projects = Project.objects.visible_to(request.user).filter(archived=False)
    return render(request, 'projects/dashboard.html', {'projects': projects})


@login_required
@role_required('admin', 'manager')
def project_create(request):
    form = ProjectForm(request.POST or None)
    if form.is_valid():
        project = form.save()
        messages.success(request, f'Project "{project.name}" created.')
        return redirect('project_detail', pk=project.pk)
    return render(request, 'projects/project_form.html', {'form': form, 'title': 'New project'})


@login_required
@role_required('admin', 'manager')
def project_edit(request, pk):
    project = _project_for(request.user, pk)
    form = ProjectForm(request.POST or None, instance=project)
    if form.is_valid():
        form.save()
        messages.success(request, 'Project updated.')
        return redirect('project_detail', pk=project.pk)
    return render(request, 'projects/project_form.html', {'form': form, 'title': f'Edit {project.name}'})


@login_required
def project_detail(request, pk):
    project = _project_for(request.user, pk)
    modules = project.modules.filter(archived=False).prefetch_related('submodules')
    return render(request, 'projects/project_detail.html', {
        'project': project, 'modules': modules,
        'module_form': ModuleForm(), 'submodule_form': SubModuleForm(),
    })


@login_required
@role_required(*CASE_EDITORS)
@require_POST
def module_add(request, pk):
    project = _project_for(request.user, pk)
    form = ModuleForm(request.POST)
    if form.is_valid():
        try:
            with transaction.atomic():
                Module.objects.create(project=project, name=form.cleaned_data['name'].strip())
        except IntegrityError:
            messages.error(request, 'That module already exists in this project.')
    else:
        messages.error(request, 'Enter a module name.')
    return redirect('project_detail', pk=pk)


@login_required
@role_required(*CASE_EDITORS)
@require_POST
def submodule_add(request, pk, module_id):
    project = _project_for(request.user, pk)
    module = get_object_or_404(project.modules, pk=module_id)
    form = SubModuleForm(request.POST)
    if form.is_valid():
        try:
            with transaction.atomic():
                module.submodules.create(name=form.cleaned_data['name'].strip())
        except IntegrityError:
            messages.error(request, 'That sub-module already exists in this module.')
    else:
        messages.error(request, 'Enter a sub-module name.')
    return redirect('project_detail', pk=pk)


@login_required
def team(request, pk):
    project = _project_for(request.user, pk)
    can_edit = request.user.role in ('admin', 'manager')
    if request.method == 'POST' and not can_edit:
        raise PermissionDenied
    old = {'backend': project.backend_dev, 'frontend': project.frontend_dev, 'ba': project.ba}
    form = TeamForm(request.POST or None, instance=project)
    if can_edit and form.is_valid():
        project = form.save()
        before = set(project.members.values_list('pk', flat=True))
        project.members.add(*[u for u in (project.backend_dev, project.frontend_dev, project.ba) if u])
        joined = len(set(project.members.values_list('pk', flat=True)) - before)
        new = {'backend': project.backend_dev, 'frontend': project.frontend_dev, 'ba': project.ba}
        changed = False
        for role in old:
            if (old[role].pk if old[role] else None) != (new[role].pk if new[role] else None):
                changed = True
                TeamChange.objects.create(
                    project=project, role=role, changed_by=request.user,
                    old_name=old[role].display_name if old[role] else '',
                    new_name=new[role].display_name if new[role] else '')
        moved = 0
        if changed:
            from bugs.team import apply_team_change     # open bugs follow the new developers
            moved = apply_team_change(project, old, new, request.user)
        messages.success(request, 'Team saved.' + (f' {joined} person(s) added to the project.' if joined else '') + (f' {moved} open bug(s) moved to the new developer.' if moved else ''))
        return redirect('project_team', pk=project.pk)
    from accounts.models import User
    return render(request, 'projects/team.html', {'project': project, 'form': form, 'can_edit': can_edit,
                  'dev_count': User.objects.filter(is_active=True, role='developer').count(),
                  'ba_count': User.objects.filter(is_active=True, role='ba').count(),
                  'changes': project.team_changes.select_related('changed_by')[:30]})
