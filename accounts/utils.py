import csv

from django.http import HttpResponse
from django.shortcuts import resolve_url
from django.utils.http import url_has_allowed_host_and_scheme


def safe_next(request, fallback, *fallback_args):
    """Return the ?next= address only if it stays on this site (prevents open redirects)."""
    target = request.POST.get('next') or request.GET.get('next')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return resolve_url(fallback, *fallback_args)


def csv_safe(value):
    """Stop spreadsheet formulas: Excel would run a cell starting with = + - @ as a formula.
    A leading apostrophe makes it plain text."""
    return "'" + value if value[:1] in ('=', '+', '-', '@', '\t', '\r') else value


def csv_download(filename, header, rows):
    """Build a CSV download. Starts with a byte-order mark so Excel reads accents correctly,
    and every cell goes through csv_safe."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_safe('' if v is None else str(v)) for v in row])
    return response
