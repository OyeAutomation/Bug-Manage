"""Reusable logic. Phase 3 (Excel import) will call these same functions."""
from projects.models import Module, SubModule
from .models import TestCase

LAYERS = {'backend': 'backend', 'frontend': 'frontend', 'be': 'backend', 'fe': 'frontend',
          'both': 'both', 'frontend & backend': 'both', 'backend & frontend': 'both', 'frontend and backend': 'both',
          'backend and frontend': 'both', 'fe&be': 'both', 'be&fe': 'both', 'frontend/backend': 'both'}
PRIORITIES = {'high': 'high', 'medium': 'medium', 'low': 'low'}


def get_or_create_module(project, name):
    """Find a module ignoring upper/lower case, or create it."""
    name = name.strip()
    found = project.modules.filter(name__iexact=name).first()
    return found or Module.objects.create(project=project, name=name)


def get_or_create_submodule(module, name):
    name = name.strip()
    if not name:
        return None
    found = module.submodules.filter(name__iexact=name).first()
    return found or SubModule.objects.create(module=module, name=name)


def clean_row(row):
    """Validate one row of raw text. Returns (cleaned_dict, list_of_error_messages)."""
    errors = []
    data = {k: (row.get(k) or '').strip() for k in
            ('module', 'sub_module', 'title', 'steps', 'expected_result', 'layer', 'priority')}
    for field, label in (('module', 'Module'), ('title', 'Test case'), ('steps', 'Steps'),
                         ('expected_result', 'Expected result')):
        if not data[field]:
            errors.append(f'{label} is required.')
    layer = LAYERS.get(data['layer'].lower()) if data['layer'] else 'frontend'
    if layer is None:
        errors.append('Backend/Frontend must be Backend, Frontend or Frontend & Backend.')
    priority = PRIORITIES.get(data['priority'].lower()) if data['priority'] else 'medium'
    if priority is None:
        errors.append('Priority must be High, Medium or Low.')
    data['layer'], data['priority'] = layer, priority
    return data, errors


def create_case(project, user, data):
    module = get_or_create_module(project, data['module'])
    sub = get_or_create_submodule(module, data['sub_module'])
    return TestCase.objects.create(
        project=project, module=module, sub_module=sub, title=data['title'], steps=data['steps'],
        expected_result=data['expected_result'], layer=data['layer'], priority=data['priority'],
        created_by=user)


def delete_case(case):
    """Delete a test case that was never executed. Its 'not run' rows are removed from runs first.
    A case that has real results keeps them (run history must not change), so it cannot be deleted."""
    from django.db import transaction
    if case.results.exclude(result='not_run').exists():
        return False
    with transaction.atomic():
        case.results.all().delete()
        case.delete()
    return True


def archive_cases(cases):
    """Archive cases and take their 'not run' rows out of runs that are still open."""
    from django.db import transaction
    with transaction.atomic():
        for case in cases:
            case.results.filter(result='not_run', run__status='open').delete()
            case.archived = True
            case.save(update_fields=['archived', 'updated_at'])
