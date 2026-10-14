from django.test import TestCase as DjangoTestCase
from django.urls import reverse

from accounts.models import User
from projects.models import Module, Project
from .models import TestCase


class CaseTests(DjangoTestCase):
    def setUp(self):
        self.qa = User.objects.create_user('qa1', password='x', role='qa', first_name='Aisha', last_name='K')
        self.dev = User.objects.create_user('dev1', password='x', role='developer')
        self.p = Project.objects.create(name='Checkout App'); self.p.members.add(self.qa, self.dev)
        self.p2 = Project.objects.create(name='Other'); self.p2.members.add(self.qa)
        self.mod = Module.objects.create(project=self.p, name='Payments')
        self.sub = self.mod.submodules.create(name='Card')

    def make(self, title='Pay with card', project=None, **kw):
        project = project or self.p
        mod = kw.pop('module', None) or (self.mod if project == self.p else Module.objects.create(project=project, name='M'))
        return TestCase.objects.create(project=project, module=mod, title=title, steps='s', expected_result='e',
                                       created_by=self.qa, **kw)

    def url(self, name, *args, project=None):
        return reverse(name, args=[(project or self.p).pk, *args])

    def test_numbers_count_per_project(self):
        a, b, c = self.make('A'), self.make('B'), self.make('C', project=self.p2)
        self.assertEqual((a.code, b.code, c.code), ('TC-1', 'TC-2', 'TC-1'))

    def test_create_via_form_and_submodule_must_match_module(self):
        self.client.force_login(self.qa)
        other = Module.objects.create(project=self.p, name='Cart'); osub = other.submodules.create(name='X')
        bad = {'module': self.mod.pk, 'sub_module': osub.pk, 'title': 't', 'steps': 's',
               'expected_result': 'e', 'layer': 'frontend', 'priority': 'high'}
        self.client.post(self.url('case_create'), bad)
        self.assertEqual(TestCase.objects.count(), 0)
        bad['sub_module'] = self.sub.pk
        self.client.post(self.url('case_create'), bad)
        self.assertEqual(TestCase.objects.get().created_by, self.qa)

    def test_developer_can_view_but_not_create(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(self.url('case_list')).status_code, 200)
        self.assertEqual(self.client.get(self.url('case_create')).status_code, 403)
        self.assertEqual(self.client.get(self.url('quick_add')).status_code, 403)

    def test_clone_gets_next_number(self):
        c = self.make('Original'); self.client.force_login(self.qa)
        self.client.post(self.url('case_clone', c.pk))
        self.assertEqual(TestCase.objects.get(number=2).title, 'Copy of Original')

    def test_search_and_filters(self):
        self.make('Login works', layer='backend'); self.make('Pay by card', priority='high')
        self.client.force_login(self.qa)
        def titles(qs):
            r = self.client.get(self.url('case_list') + qs); return [c.title for c in r.context['page']]
        self.assertEqual(titles('?q=login'), ['Login works'])
        self.assertEqual(titles('?q=TC-2'), ['Pay by card'])
        self.assertEqual(titles('?layer=backend'), ['Login works'])
        self.assertEqual(titles('?priority=high'), ['Pay by card'])

    def test_bulk_archive_and_hidden_from_default_list(self):
        c = self.make(); self.client.force_login(self.qa)
        self.client.post(self.url('cases_bulk'), {'ids': [c.pk], 'action': 'archive'})
        self.assertEqual(len(self.client.get(self.url('case_list')).context['page']), 0)
        self.assertEqual(len(self.client.get(self.url('case_list') + '?archived=1').context['page']), 1)

    def test_cannot_touch_other_projects_cases(self):
        c = self.make(project=self.p2); self.client.force_login(self.dev)   # dev is not in p2
        self.assertEqual(self.client.get(self.url('case_list', project=self.p2)).status_code, 404)

    def test_csv_export_columns_bom_and_values(self):
        self.make('Pay with card', sub_module=self.sub, layer='backend'); self.client.force_login(self.dev)
        body = self.client.get(self.url('cases_export')).content.decode('utf-8')
        self.assertTrue(body.startswith('\ufeff'))
        lines = body.lstrip('\ufeff').splitlines()
        self.assertEqual(lines[0], 'MODULE,SUB-MODULE,TEST CASE,STEPS TO REPRODUCE,EXPECTED RESULT,ACTUAL RESULT,BACKEND/FRONTEND,DATE,QA NAME')
        self.assertTrue(lines[1].startswith('Payments,Card,Pay with card,s,e,,Backend,'))
        self.assertTrue(lines[1].endswith(',Aisha K'))

    def post_grid(self, rows):
        keys = ['module', 'sub_module', 'title', 'steps', 'expected_result', 'layer', 'priority']
        return self.client.post(self.url('quick_add'), {k: [r.get(k, '') for r in rows] for k in keys})

    def test_quick_add_creates_modules_and_is_all_or_nothing(self):
        self.client.force_login(self.qa)
        good = dict(module='payments', sub_module='Wallet', title='T1', steps='s', expected_result='e', layer='Backend', priority='High')
        self.post_grid([good, dict(good, title='')])           # second row invalid
        self.assertEqual(TestCase.objects.count(), 0)
        self.post_grid([good, dict(good, module='Search', sub_module='', title='T2')])
        self.assertEqual(TestCase.objects.count(), 2)
        self.assertEqual(self.p.modules.filter(name__iexact='payments').count(), 1)  # matched ignoring case
        self.assertTrue(self.p.modules.filter(name='Search').exists())
        self.assertEqual(TestCase.objects.get(title='T1').layer, 'backend')

    def test_bulk_next_cannot_leave_the_site(self):
        c = self.make(); self.client.force_login(self.qa)
        r = self.client.post(self.url('cases_bulk'), {'ids': [c.pk], 'action': 'archive', 'next': 'https://evil.example/'})
        self.assertEqual(r['Location'], self.url('case_list'))


class DeleteAndBaTests(DjangoTestCase):
    def setUp(self):
        mk = lambda n, r: User.objects.create_user(n, password='x', role=r)
        self.qa, self.ba, self.dev = mk('qa1', 'qa'), mk('bea', 'ba'), mk('dev1', 'developer')
        self.p = Project.objects.create(name='Shop'); self.p.members.add(self.qa, self.ba, self.dev)
        self.mod = Module.objects.create(project=self.p, name='Pay')

    def case(self, title='T'):
        return TestCase.objects.create(project=self.p, module=self.mod, title=title, steps='s', expected_result='e', created_by=self.qa)

    def u(self, name, *a):
        return reverse(name, args=[self.p.pk, *a])

    def test_ba_can_add_edit_and_delete_cases(self):
        self.client.force_login(self.ba)
        body = {'module': self.mod.pk, 'title': 'By BA', 'steps': 's', 'expected_result': 'e', 'layer': 'both', 'priority': 'high'}
        self.client.post(self.u('case_create'), body); c = TestCase.objects.get()
        self.assertEqual(c.created_by, self.ba)
        self.client.post(self.u('case_edit', c.pk), {**body, 'title': 'Renamed'}); c.refresh_from_db()
        self.assertEqual(c.title, 'Renamed')
        self.client.post(self.u('case_delete', c.pk)); self.assertEqual(TestCase.objects.count(), 0)

    def test_ba_can_use_quick_add_and_import_page(self):
        self.client.force_login(self.ba)
        self.assertEqual(self.client.get(self.u('quick_add')).status_code, 200)
        self.assertEqual(self.client.get(self.u('import_home')).status_code, 200)

    def test_developer_cannot_delete(self):
        c = self.case(); self.client.force_login(self.dev)
        self.assertEqual(self.client.post(self.u('case_delete', c.pk)).status_code, 403)
        self.assertEqual(TestCase.objects.count(), 1)

    def test_delete_asks_first_and_removes_waiting_rows_from_open_runs(self):
        from runs.models import TestResult, TestRun
        c = self.case(); run = TestRun.objects.create(project=self.p, name='R', created_by=self.qa); run.sync_cases()
        self.client.force_login(self.qa)
        self.assertContains(self.client.get(self.u('case_delete', c.pk)), 'never been executed')
        self.assertEqual(TestCase.objects.count(), 1)                         # a GET never deletes
        self.client.post(self.u('case_delete', c.pk))
        self.assertEqual((TestCase.objects.count(), TestResult.objects.count()), (0, 0))

    def test_case_with_results_cannot_be_deleted(self):
        from runs.models import TestResult, TestRun
        c = self.case(); run = TestRun.objects.create(project=self.p, name='R', created_by=self.qa)
        TestResult.objects.create(run=run, test_case=c, result='pass'); self.client.force_login(self.qa)
        self.assertContains(self.client.get(self.u('case_delete', c.pk)), 'Archive it instead')
        self.client.post(self.u('case_delete', c.pk))
        self.assertEqual(TestCase.objects.count(), 1)

    def test_bulk_delete_removes_unused_and_reports_blocked(self):
        from runs.models import TestResult, TestRun
        a, b = self.case('A'), self.case('B'); run = TestRun.objects.create(project=self.p, name='R', created_by=self.qa)
        TestResult.objects.create(run=run, test_case=b, result='fail'); self.client.force_login(self.qa)
        r = self.client.post(self.u('cases_bulk'), {'ids': [a.pk, b.pk], 'action': 'delete'}, follow=True)
        self.assertEqual([c.title for c in TestCase.objects.all()], ['B'])
        self.assertContains(r, 'could not be deleted')

    def test_archiving_takes_waiting_rows_out_of_open_runs_only(self):
        from runs.models import TestResult, TestRun
        c = self.case(); open_run = TestRun.objects.create(project=self.p, name='Open', created_by=self.qa)
        done = TestRun.objects.create(project=self.p, name='Done', created_by=self.qa, status='closed')
        TestResult.objects.create(run=open_run, test_case=c); TestResult.objects.create(run=done, test_case=c, result='pass')
        self.client.force_login(self.qa); self.client.post(self.u('cases_bulk'), {'ids': [c.pk], 'action': 'archive'})
        c.refresh_from_db()
        self.assertTrue(c.archived)
        self.assertEqual((open_run.results.count(), done.results.count()), (0, 1))
