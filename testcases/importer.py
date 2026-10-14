"""Reading, checking and applying Excel uploads. Views stay thin; the rules live here."""
import re
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.datavalidation import DataValidation

from .models import TestCase
from .services import clean_row, create_case

HEADERS = ['MODULE', 'SUB-MODULE', 'TEST CASE', 'STEPS', 'EXPECTED RESULT', 'BACKEND/FRONTEND', 'PRIORITY']
FIELD_FOR = {'MODULE': 'module', 'SUB-MODULE': 'sub_module', 'TEST CASE': 'title', 'STEPS': 'steps',
             'EXPECTED RESULT': 'expected_result', 'BACKEND/FRONTEND': 'layer', 'PRIORITY': 'priority'}
# Other spellings we also accept, so a CSV exported from this app can be re-imported.
ALIASES = {'SUBMODULE': 'SUB-MODULE', 'SUB MODULE': 'SUB-MODULE', 'STEPS TO REPRODUCE': 'STEPS',
           'TEST CASES': 'TEST CASE', 'TITLE': 'TEST CASE', 'EXPECTED': 'EXPECTED RESULT',
           'LAYER': 'BACKEND/FRONTEND', 'BACKEND / FRONTEND': 'BACKEND/FRONTEND'}
REQUIRED = ['MODULE', 'TEST CASE', 'STEPS', 'EXPECTED RESULT']
MAX_ROWS = 5000
SHEET = 'Test cases'


class ImportFileError(Exception):
    """A problem with the whole file (not one row). The message is shown to the user."""


def _norm_header(value):
    h = re.sub(r'\s+', ' ', str(value or '').replace('_', ' ')).strip().upper()
    return ALIASES.get(h, h)


def _text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)          # Excel stores 5 as 5.0
    return str(value).strip()


def _key(module, sub, title):
    return (module.strip().lower(), sub.strip().lower(), title.strip().lower())


def parse_upload(file, project):
    """Return a list of row dicts, each marked new / duplicate / invalid."""
    try:
        wb = load_workbook(file, read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, KeyError, OSError):
        raise ImportFileError('This is not a valid .xlsx file. Download the template and try again.')
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]

    rows_iter = ws.iter_rows(values_only=True)
    columns, header_row = None, 0
    for header_row, cells in enumerate(rows_iter, start=1):
        if any(_text(c) for c in cells):
            columns = [FIELD_FOR.get(_norm_header(c)) for c in cells]
            names = {_norm_header(c) for c in cells}
            break
    if columns is None:
        raise ImportFileError('The file is empty.')
    missing = [h for h in REQUIRED if h not in names]
    if missing:
        raise ImportFileError('Missing column(s): ' + ', '.join(missing) + '. Use the template headers.')

    existing = {}
    for c in project.test_cases.select_related('module', 'sub_module'):
        existing[_key(c.module.name, c.sub_module.name if c.sub_module else '', c.title)] = c.pk

    parsed, seen = [], {}
    for sheet_row, cells in enumerate(rows_iter, start=header_row + 1):
        raw = {}
        for field, cell in zip(columns, cells):
            if field:
                raw[field] = _text(cell)
        if not any(raw.values()):
            continue                                   # blank line
        if len(parsed) >= MAX_ROWS:
            raise ImportFileError(f'Too many rows. Split the file into parts of {MAX_ROWS} rows or fewer.')
        data, errors = clean_row(raw)
        row = dict(data, n=sheet_row, errors=errors, existing_id=None,
                   layer_given=bool(raw.get('layer')), priority_given=bool(raw.get('priority')),
                   layer_raw=raw.get('layer', ''), priority_raw=raw.get('priority', ''))
        if not errors:
            key = _key(data['module'], data['sub_module'], data['title'])
            if key in seen:
                row['errors'] = [f'Same module, sub-module and test case as row {seen[key]} in this file.']
            else:
                seen[key] = sheet_row
                row['existing_id'] = existing.get(key)
        row['status'] = ('invalid' if row['errors'] else 'duplicate' if row['existing_id'] else 'new')
        parsed.append(row)
    if not parsed:
        raise ImportFileError('No test cases found. Fill in rows under the header and try again.')
    return parsed


def apply_batch(batch, user, policy):
    """Save the valid rows. Called inside a transaction by the view, so it is all or nothing."""
    project = batch.project
    created = updated = skipped = 0
    for row in batch.rows:
        if row['status'] == 'invalid':
            continue
        case = TestCase.objects.filter(pk=row['existing_id'], project=project).first() if row['existing_id'] else None
        if case is None:
            create_case(project, user, row)
            created += 1
        elif policy == 'update':
            case.steps, case.expected_result = row['steps'], row['expected_result']
            if row['layer_given']:
                case.layer = row['layer']
            if row['priority_given']:
                case.priority = row['priority']
            case.save()
            updated += 1
        else:
            skipped += 1
    batch.created_count, batch.updated_count, batch.skipped_count = created, updated, skipped
    batch.rejected_count = batch.count('invalid')
    batch.policy, batch.status = policy, batch.Status.DONE
    batch.save()


def _style_header(ws, widths):
    fill = PatternFill('solid', fgColor='0F766E')
    for col, (cell, width) in enumerate(zip(ws[1], widths), start=1):
        cell.font, cell.fill = Font(bold=True, color='FFFFFF'), fill
        ws.column_dimensions[cell.column_letter].width = width
    ws.freeze_panes = 'A2'


def _set_text(cell, value):
    cell.value = value
    cell.data_type = 's'            # always store as text, so a value like =1+1 never runs as a formula
    cell.alignment = Alignment(wrap_text=True, vertical='top')


def build_template():
    wb = Workbook()
    ws = wb.active; ws.title = SHEET
    ws.append(HEADERS)
    _style_header(ws, [20, 20, 40, 50, 40, 18, 12])
    layers = DataValidation(type='list', formula1='"Backend,Frontend,Frontend & Backend"', allow_blank=True)
    priorities = DataValidation(type='list', formula1='"High,Medium,Low"', allow_blank=True)
    ws.add_data_validation(layers); ws.add_data_validation(priorities)
    layers.add(f'F2:F{MAX_ROWS + 1}'); priorities.add(f'G2:G{MAX_ROWS + 1}')
    help_ws = wb.create_sheet('How to fill')
    for line in [
        ['Fill the "Test cases" sheet. One row = one test case. Do not rename or reorder the headers.'],
        ['MODULE, TEST CASE, STEPS and EXPECTED RESULT are required.'],
        ['SUB-MODULE is optional. Modules and sub-modules that do not exist yet are created for you.'],
        ['BACKEND/FRONTEND: Backend, Frontend or Frontend & Backend (blank = Frontend). PRIORITY: High, Medium or Low (blank = Medium).'],
        ['For several steps, put each step on its own line inside the cell (Alt+Enter in Excel).'],
        [f'A file can hold up to {MAX_ROWS} test cases.'],
        [], ['Example'],
        HEADERS,
        ['Payments', 'Card', 'Expired card shows an error', '1. Open checkout\n2. Enter an expired card\n3. Click Pay',
         'A "Card has expired" message appears', 'Frontend', 'High']]:
        help_ws.append(line)
    help_ws.column_dimensions['A'].width = 100
    for cell in help_ws[9]:
        cell.font = Font(bold=True)
    for cell in help_ws[10]:
        cell.alignment = Alignment(wrap_text=True, vertical='top')
    out = BytesIO(); wb.save(out)
    return out.getvalue()


def build_error_report(batch):
    """Rejected rows, in the template layout plus an ERROR column. Fix them and upload again."""
    wb = Workbook(); ws = wb.active; ws.title = SHEET
    ws.append(HEADERS + ['ERROR'])
    _style_header(ws, [20, 20, 40, 50, 40, 18, 12, 50])
    for row in batch.rows:
        if row['status'] != 'invalid':
            continue
        ws.append([''] * 8)
        values = [row['module'], row['sub_module'], row['title'], row['steps'], row['expected_result'],
                  row['layer_raw'], row['priority_raw'], ' '.join(row['errors'])]
        for cell, value in zip(ws[ws.max_row], values):
            _set_text(cell, value)
    out = BytesIO(); wb.save(out)
    return out.getvalue()
