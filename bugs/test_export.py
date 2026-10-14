import csv
import io

from django.test import TestCase as DjangoTestCase
from django.urls import reverse

from accounts.models import User
from projects.models import Module, Project
from runs.models import TestResult, TestRun
from testcases.models import TestCase
from bugs.models import Bug

SPEC = ['MODULE', 'SUB-MODULE', 'TEST CASE', 'STEPS TO REPRODUCE', 'EXPECTED RESULT', 'ACTUAL RESULT',
        'BACKEND/FRONTEND', 'DATE', 'QA NAME']


def parse(response):
    text = response.content.decode('utf-8')
    assert text.startswith('\ufeff'), 'missing byte-order mark'
    return list(csv.reader(io.StringIO(text.lstrip('\ufeff'))))


class ExportTests(DjangoTestCase):
    def setUp(self):
        mk = lambda n, r, f='': User.objects.create_user(n, password='x', role=r, first_name=f)
        self.qa, self.dev = mk('qa1', 'qa', 'Aisha'), mk('dev1', 'developer', 'Rohan')
        self.p = Project.objects.create(name='Checkout App', frontend_dev=self.dev); self.p.members.add(self.qa, self.dev)
        self.mod = Module.objects.create(project=self.p, name='Payments'); self.sub = self.mod.submodules.create(name='Card')
        self.case = TestCase.objects.create(project=self.p, module=self.mod, sub_module=self.sub, title='Expired card',
                                            steps='1. Open\n2. Pay', expected_result='Error shown', layer='frontend', created_by=self.qa)
        self.run = TestRun.objects.create(project=self.p, name='Sprint 18', build='2.4.0', run_date='2026-10-14', created_by=self.qa, assigned_qa=self.qa)
        self.client.force_login(self.qa)

    def u(self, name, *a):
        return reverse(name, args=[self.p.pk, *a])

    def bug(self, **kw):
        d = dict(project=self.p, title='Expired card', module=self.mod, sub_module=self.sub, test_case=self.case, steps='1. Open\n2. Pay',
                 expected_result='Error shown', actual_result='no error', layer='frontend', reporter=self.qa, assignee=self.dev)
        return Bug.objects.create(**{**d, **kw})

    # ---------------- bugs ----------------
    def test_bug_csv_has_the_required_columns_in_order(self):
        b = self.bug()
        rows = parse(self.client.get(self.u('bugs_export')))
        self.assertEqual(rows[0], SPEC)
        self.assertEqual(rows[1], ['Payments', 'Card', 'Expired card', '1. Open\n2. Pay', 'Error shown', 'no error',
                                   'Frontend', b.created_at.strftime('%Y-%m-%d'), 'Aisha'])

    def test_bare_download_includes_closed_bugs_but_status_filter_applies(self):
        self.bug(title='Open one'); self.bug(title='Closed one', status='closed', test_case=None)
        self.assertEqual(len(parse(self.client.get(self.u('bugs_export')))), 3)                       # header + both
        self.assertEqual(len(parse(self.client.get(self.u('bugs_export') + '?status=active'))), 2)    # closed left out

    def test_export_follows_the_developer_type_filter(self):
        self.bug(layer='backend', title='B', test_case=None); self.bug(layer='frontend', title='F', test_case=None)
        rows = parse(self.client.get(self.u('bugs_export') + '?layer=backend'))
        self.assertEqual([r[2] for r in rows[1:]], ['B'])

    def test_detail_version_keeps_the_first_nine_columns_and_adds_more(self):
        b = self.bug(status='fixed', solved_by_frontend='Rohan')
        rows = parse(self.client.get(self.u('bugs_export') + '?detail=1'))
        self.assertEqual(rows[0][:9], SPEC); self.assertEqual(rows[0][9:12], ['BUG ID', 'BUG TITLE', 'STATUS'])
        r = dict(zip(rows[0], rows[1]))
        self.assertEqual((r['BUG ID'], r['STATUS'], r['ASSIGNEE'], r['FIXED BY'], r['TEST CASE ID']),
                         (b.code, 'Fixed', 'Rohan', 'Rohan (Frontend)', self.case.code))

    def test_bug_title_is_used_when_there_is_no_test_case(self):
        self.bug(title='Found by hand', test_case=None)
        self.assertEqual(parse(self.client.get(self.u('bugs_export')))[1][2], 'Found by hand')

    def test_formulas_in_bugs_are_neutralised(self):
        self.bug(title='x', test_case=None, actual_result='=HYPERLINK("http://evil")')
        self.assertIn("'=HYPERLINK", self.client.get(self.u('bugs_export')).content.decode())

    def test_bug_export_access(self):
        self.bug(); self.client.force_login(self.dev)
        self.assertEqual(self.client.get(self.u('bugs_export')).status_code, 200)          # developers can download
        outsider = User.objects.create_user('out', password='x', role='manager'); self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.u('bugs_export')).status_code, 404)
        self.client.logout(); self.assertEqual(self.client.get(self.u('bugs_export')).status_code, 302)

    def test_bug_page_links_carry_the_current_filters(self):
        page = self.client.get(self.u('bug_list') + '?layer=backend')
        self.assertContains(page, 'export.csv?layer=backend&amp;status=active')
        self.assertContains(page, 'detail=1')

    # ---------------- test cases (shared helper keeps working) ----------------
    def test_test_case_export_still_matches_the_format(self):
        rows = parse(self.client.get(self.u('cases_export')))
        self.assertEqual(rows[0], SPEC); self.assertEqual(rows[1][:3], ['Payments', 'Card', 'Expired card'])

    # ---------------- test runs ----------------
    def make_results(self):
        extra = TestCase.objects.create(project=self.p, module=self.mod, title='Second', steps='s', expected_result='e', layer='backend', created_by=self.qa)
        self.run.sync_cases()
        a, b = self.run.results.get(test_case=self.case), self.run.results.get(test_case=extra)
        return a, b

    def test_run_csv_lists_every_case_with_result_and_skipped_last(self):
        a, b = self.make_results()
        self.client.post(self.u('run_set_result', self.run.pk, a.pk), {'result': 'skip'})
        self.client.post(self.u('run_set_result', self.run.pk, b.pk), {'result': 'fail', 'note': 'wrong total'})
        rows = parse(self.client.get(self.u('run_export', self.run.pk)))
        self.assertEqual(rows[0][:9], SPEC); self.assertEqual(rows[0][9:], ['TEST ID', 'RESULT', 'BUG', 'RUN', 'VERSION', 'RUN DATE'])
        self.assertEqual([r[2] for r in rows[1:]], ['Second', 'Expired card'])                    # skipped one at the end
        failed = dict(zip(rows[0], rows[1])); skipped = dict(zip(rows[0], rows[2]))
        self.assertEqual((failed['RESULT'], failed['ACTUAL RESULT'], failed['QA NAME'], failed['BUG'], failed['RUN'], failed['VERSION'], failed['RUN DATE']),
                         ('Fail', 'wrong total', 'Aisha', 'BUG-1', 'Sprint 18', '2.4.0', '2026-10-14'))
        self.assertEqual((skipped['RESULT'], skipped['BUG']), ('Skipped', ''))

    def test_not_run_cases_have_blank_tester_and_date(self):
        self.make_results()
        r = dict(zip(*parse(self.client.get(self.u('run_export', self.run.pk)))[:2]))
        self.assertEqual((r['RESULT'], r['QA NAME'], r['DATE']), ('Not run', '', ''))

    def test_run_csv_can_be_limited_to_one_result(self):
        a, b = self.make_results()
        self.client.post(self.u('run_set_result', self.run.pk, a.pk), {'result': 'pass'})
        rows = parse(self.client.get(self.u('run_export', self.run.pk) + '?result=pass'))
        self.assertEqual([r[2] for r in rows[1:]], ['Expired card'])

    def test_run_download_buttons_exist(self):
        self.make_results()
        self.assertContains(self.client.get(self.u('run_detail', self.run.pk)), f'/runs/{self.run.pk}/export.csv')
        self.assertContains(self.client.get(self.u('run_list')), 'Download summary CSV')

    def test_run_summary_csv(self):
        a, b = self.make_results()
        self.client.post(self.u('run_set_result', self.run.pk, a.pk), {'result': 'pass'})
        self.client.post(self.u('run_set_result', self.run.pk, b.pk), {'result': 'skip'})
        rows = parse(self.client.get(self.u('run_list_export')))
        r = dict(zip(rows[0], rows[1]))
        self.assertEqual((r['RUN'], r['VERSION'], r['QA'], r['STATUS'], r['TOTAL'], r['PASS'], r['SKIPPED'], r['EXECUTED %']),
                         ('Sprint 18', '2.4.0', 'Aisha', 'Open', '2', '1', '1', '50'))

    def test_run_exports_access(self):
        self.make_results(); self.client.force_login(self.dev)
        self.assertEqual(self.client.get(self.u('run_export', self.run.pk)).status_code, 200)
        self.assertEqual(self.client.get(self.u('run_list_export')).status_code, 200)
        outsider = User.objects.create_user('out', password='x', role='manager'); self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.u('run_export', self.run.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.u('run_list_export')).status_code, 404)
