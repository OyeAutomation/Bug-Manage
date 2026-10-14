from django.test import TestCase as DjangoTestCase
from django.urls import reverse

from accounts.models import User
from bugs.models import Bug
from projects.models import Module, Project
from testcases.models import TestCase
from .models import TestResult, TestRun


class RunTests(DjangoTestCase):
    def setUp(self):
        mk = lambda n, r: User.objects.create_user(n, password='x', role=r, first_name=n.title())
        self.qa, self.dev, self.mgr, self.ba = mk('qa1', 'qa'), mk('dev1', 'developer'), mk('mgr', 'manager'), mk('bea', 'ba')
        self.p = Project.objects.create(name='Checkout'); self.p.members.add(self.qa, self.dev, self.mgr, self.ba)
        self.pay = Module.objects.create(project=self.p, name='Payments')
        self.cart = Module.objects.create(project=self.p, name='Cart')
        self.c1, self.c2 = self.mk_case('A'), self.mk_case('B')
        self.archived = self.mk_case('Old', module=self.cart, archived=True)
        self.client.force_login(self.qa)

    def mk_case(self, title, module=None, **kw):
        return TestCase.objects.create(project=self.p, module=module or self.pay, title=title, steps='s',
                                       expected_result='e', created_by=self.qa, **kw)

    def u(self, name, *a):
        return reverse(name, args=[self.p.pk, *a])

    def form(self, **over):
        return {'name': 'Sprint 1', 'run_date': '2026-10-14', 'build': '2.4.0', 'environment': 'QA',
                'assigned_qa': self.qa.pk, **over}

    def make_run(self, **over):
        self.client.post(self.u('run_create'), self.form(**over))
        return TestRun.objects.latest('id')

    def result(self, run, case):
        return run.results.get(test_case=case)

    def mark(self, run, case, value, note=''):
        return self.client.post(self.u('run_set_result', run.pk, self.result(run, case).pk), {'result': value, 'note': note})

    def order(self, run):
        return [r.test_case.title for r in run.results.ordered()]

    # ---- creating a run ----
    def test_run_has_name_date_version_qa_and_all_active_cases(self):
        run = self.make_run()
        self.assertEqual((run.name, str(run.run_date), run.build, run.assigned_qa), ('Sprint 1', '2026-10-14', '2.4.0', self.qa))
        self.assertEqual(sorted(self.order(run)), ['A', 'B'])                  # archived case is left out
        self.assertEqual(set(run.results.values_list('result', flat=True)), {'not_run'})

    def test_every_field_is_required(self):
        for missing in ('name', 'run_date', 'build', 'assigned_qa'):
            self.client.post(self.u('run_create'), self.form(**{missing: ''}))
        self.assertEqual(TestRun.objects.count(), 0)

    def test_qa_must_be_a_project_member_who_can_test(self):
        outsider = User.objects.create_user('out', password='x', role='qa')
        for who in (self.dev, self.ba, outsider):
            self.client.post(self.u('run_create'), self.form(assigned_qa=who.pk))
        self.assertEqual(TestRun.objects.count(), 0)

    def test_an_admin_member_can_be_the_qa_of_a_run(self):
        boss = User.objects.create_superuser('boss', password='x'); self.p.members.add(boss)
        self.client.force_login(boss)
        self.client.post(self.u('run_create'), self.form(name='Solo run', assigned_qa=boss.pk))
        self.assertEqual(TestRun.objects.get(name='Solo run').assigned_qa, boss)

    def test_run_needs_test_cases(self):
        empty = Project.objects.create(name='Empty'); empty.members.add(self.qa)
        r = self.client.post(reverse('run_create', args=[empty.pk]), self.form())
        self.assertContains(r, 'no active test cases')
        self.assertEqual(TestRun.objects.count(), 0)

    def test_new_cases_appear_in_an_open_run_but_not_a_closed_one(self):
        run = self.make_run(); self.mk_case('C')
        self.assertEqual(len(self.client.get(self.u('run_detail', run.pk)).context['results']), 3)
        self.client.post(self.u('run_close', run.pk)); self.mk_case('D')
        self.assertEqual(len(self.client.get(self.u('run_detail', run.pk)).context['results']), 3)

    # ---- pass / fail / skip ----
    def test_pass_moves_to_next_case(self):
        run = self.make_run()
        r = self.mark(run, self.c1, 'pass', 'ok')
        self.assertRedirects(r, self.u('run_execute', run.pk, self.result(run, self.c2).pk))
        res = self.result(run, self.c1)
        self.assertEqual((res.result, res.tester, res.note), ('pass', self.qa, 'ok')); self.assertIsNotNone(res.executed_at)

    def test_skipped_case_goes_to_the_end_of_the_run(self):
        c3 = self.mk_case('C'); run = self.make_run()
        self.assertEqual(self.order(run), ['A', 'B', 'C'])
        r = self.mark(run, self.c1, 'skip')
        self.assertEqual(self.order(run), ['B', 'C', 'A'])
        self.assertRedirects(r, self.u('run_execute', run.pk, self.result(run, self.c2).pk))
        shown = [x.test_case.title for x in self.client.get(self.u('run_detail', run.pk)).context['results']]
        self.assertEqual(shown, ['B', 'C', 'A'])                                 # also at the bottom of the run page

    def test_skipped_cases_come_back_only_after_everything_else(self):
        c3 = self.mk_case('C'); run = self.make_run()
        self.mark(run, self.c1, 'skip')
        self.mark(run, self.c2, 'pass')
        r = self.mark(run, c3, 'pass')
        self.assertRedirects(r, self.u('run_execute', run.pk, self.result(run, self.c1).pk))     # now the skipped one
        r = self.mark(run, self.c1, 'pass')
        self.assertRedirects(r, self.u('run_detail', run.pk))                                    # finished

    def test_skipping_the_only_remaining_case_returns_to_run_page(self):
        run = self.make_run(); self.mark(run, self.c1, 'pass')
        r = self.mark(run, self.c2, 'skip')
        self.assertRedirects(r, self.u('run_detail', run.pk))

    def test_start_button_points_to_skipped_when_nothing_else_is_left(self):
        run = self.make_run(); self.mark(run, self.c1, 'skip'); self.mark(run, self.c2, 'pass')
        ctx = self.client.get(self.u('run_detail', run.pk)).context
        self.assertTrue(ctx['only_skipped']); self.assertEqual(ctx['first_pending'], self.result(run, self.c1).pk)

    def test_fail_creates_a_bug_and_moves_on(self):
        run = self.make_run()
        r = self.mark(run, self.c1, 'fail', 'no error shown')
        bug = Bug.objects.get()
        self.assertEqual((bug.actual_result, bug.test_case, bug.reporter, bug.build), ('no error shown', self.c1, self.qa, '2.4.0'))
        self.assertRedirects(r, self.u('run_execute', run.pk, self.result(run, self.c2).pk))

    def test_invalid_result_rejected(self):
        run = self.make_run()
        self.mark(run, self.c1, 'not_run'); self.mark(run, self.c1, 'nonsense')
        self.assertEqual(self.result(run, self.c1).result, 'not_run')

    # ---- permissions and closing ----
    def test_closed_run_is_read_only_until_manager_reopens(self):
        run = self.make_run(); self.client.post(self.u('run_close', run.pk))
        self.mark(run, self.c1, 'pass'); self.assertEqual(self.result(run, self.c1).result, 'not_run')
        self.assertEqual(self.client.post(self.u('run_reopen', run.pk)).status_code, 403)
        self.client.force_login(self.mgr); self.client.post(self.u('run_reopen', run.pk))
        self.client.force_login(self.qa); self.mark(run, self.c1, 'pass')
        self.assertEqual(self.result(run, self.c1).result, 'pass')

    def test_developer_can_view_but_not_execute_or_create(self):
        run = self.make_run(); self.client.force_login(self.dev); res = self.result(run, self.c1)
        self.assertEqual(self.client.get(self.u('run_detail', run.pk)).status_code, 200)
        self.assertEqual(self.client.get(self.u('run_execute', run.pk, res.pk)).status_code, 200)
        self.assertEqual(self.client.post(self.u('run_set_result', run.pk, res.pk), {'result': 'pass'}).status_code, 403)
        self.assertEqual(self.client.get(self.u('run_create')).status_code, 403)

    def test_ba_can_create_a_run_but_not_execute_it(self):
        self.client.force_login(self.ba)
        self.assertEqual(self.client.get(self.u('run_create')).status_code, 200)
        self.client.post(self.u('run_create'), self.form(name='BA run')); run = TestRun.objects.get(name='BA run')
        self.assertEqual(run.created_by, self.ba)
        res = self.result(run, self.c1)
        self.assertEqual(self.client.post(self.u('run_set_result', run.pk, res.pk), {'result': 'pass'}).status_code, 403)

    def test_summary_counts_skipped_as_not_finished(self):
        run = self.make_run(); self.mark(run, self.c1, 'pass'); self.mark(run, self.c2, 'skip')
        s = run.summary()
        self.assertEqual((s['total'], s['done'], s['pass'], s['skip'], s['percent']), (2, 1, 1, 1, 50))
