from django.test import TestCase as DjangoTestCase
from django.urls import reverse

from accounts.models import User
from projects.models import Module, Project
from runs.models import TestResult, TestRun
from testcases.models import TestCase
from .models import Bug
from .workflow import allowed_targets


class BugTests(DjangoTestCase):
    def setUp(self):
        self.qa = User.objects.create_user('qa1', password='x', role='qa', first_name='Aisha')
        self.dev = User.objects.create_user('dev1', password='x', role='developer', first_name='Rohan')
        self.mgr = User.objects.create_user('mgr', password='x', role='manager')
        self.p = Project.objects.create(name='Checkout'); self.p.members.add(self.qa, self.dev, self.mgr)
        self.mod = Module.objects.create(project=self.p, name='Payments'); self.sub = self.mod.submodules.create(name='Card')
        self.case = TestCase.objects.create(project=self.p, module=self.mod, sub_module=self.sub, title='Expired card',
                                            steps='1. Open\n2. Pay', expected_result='Error shown', layer='frontend',
                                            created_by=self.qa)
        self.run = TestRun.objects.create(project=self.p, name='Sprint 1', build='2.4', environment='QA', created_by=self.qa)
        self.res = TestResult.objects.create(run=self.run, test_case=self.case, result='fail', note='no error')
        self.client.force_login(self.qa)

    def u(self, name, *a):
        return reverse(name, args=[self.p.pk, *a])

    def make_bug(self, **kw):
        d = dict(project=self.p, title='Bug', module=self.mod, steps='s', expected_result='e', actual_result='a', reporter=self.qa)
        return Bug.objects.create(**{**d, **kw})

    def body(self, **kw):
        d = {'title': 'T', 'module': self.mod.pk, 'sub_module': self.sub.pk, 'steps': 's', 'expected_result': 'e',
             'actual_result': 'a', 'layer': 'frontend', 'severity': 'major', 'priority': 'high', 'environment': 'QA',
             'build': '1', 'assignee': self.dev.pk, 'release_phase': 'qa'}
        return {**d, **kw}

    def status(self, bug, target, user, reason='', seen=None):
        bug.refresh_from_db()            # like a person reloading the page: use the real current status
        self.client.force_login(user)
        return self.client.post(self.u('bug_status', bug.pk), {'target': target, 'reason': reason, 'seen_status': seen or bug.status}, follow=True)

    # ---- raising bugs ----
    def test_form_is_prefilled_from_failed_result(self):
        r = self.client.get(self.u('bug_create') + f'?result={self.res.pk}')
        f = r.context['form']
        self.assertEqual((f.initial['title'], f.initial['steps'], f.initial['environment'], f.initial['build'], f.initial['actual_result']),
                         ('Expired card', '1. Open\n2. Pay', 'QA', '2.4', 'no error'))

    def test_creating_links_bug_to_case_run_result_and_logs_history(self):
        other = TestResult.objects.create(run=self.run, test_case=TestCase.objects.create(
            project=self.p, module=self.mod, title='Next', steps='s', expected_result='e', created_by=self.qa))
        r = self.client.post(self.u('bug_create'), {**self.body(), 'result': self.res.pk})
        bug = Bug.objects.get()
        self.assertEqual((bug.test_case, bug.run, bug.result, bug.reporter, bug.code), (self.case, self.run, self.res, self.qa, 'BUG-1'))
        self.assertEqual(bug.history.get().field, 'created')
        self.assertRedirects(r, self.u('run_execute', self.run.pk, other.pk))   # keeps testing: next pending case

    def test_manual_bug_without_test_case(self):
        r = self.client.post(self.u('bug_create'), self.body())
        self.assertRedirects(r, self.u('bug_detail', Bug.objects.get().pk))

    def test_similar_open_bug_triggers_warning(self):
        self.make_bug(test_case=self.case)
        r = self.client.get(self.u('bug_create') + f'?result={self.res.pk}')
        self.assertEqual(len(r.context['similar']), 1)

    def test_numbers_are_per_project(self):
        p2 = Project.objects.create(name='Other'); m2 = Module.objects.create(project=p2, name='M')
        a = self.make_bug(); b = self.make_bug(); c = self.make_bug(project=p2, module=m2)
        self.assertEqual((a.code, b.code, c.code), ('BUG-1', 'BUG-2', 'BUG-1'))

    def test_submodule_must_match_module(self):
        other = Module.objects.create(project=self.p, name='Cart')
        self.client.post(self.u('bug_create'), self.body(module=other.pk))
        self.assertEqual(Bug.objects.count(), 0)

    # ---- lifecycle ----
    def test_role_targets(self):
        self.assertEqual([v for v, _ in allowed_targets('open', 'developer')], ['in_progress'])
        self.assertEqual([v for v, _ in allowed_targets('in_progress', 'developer')], ['open', 'fixed'])
        self.assertEqual([v for v, _ in allowed_targets('fixed', 'qa')], ['retest', 'closed', 'reopened'])
        self.assertEqual(allowed_targets('open', 'developer') and [v for v, _ in allowed_targets('fixed', 'developer')], [])

    def test_happy_path_open_to_closed(self):
        bug = self.make_bug()
        self.status(bug, 'in_progress', self.dev); self.status(bug, 'fixed', self.dev)
        self.status(bug, 'retest', self.qa); self.status(bug, 'closed', self.qa)
        bug.refresh_from_db()
        self.assertEqual((bug.status, bug.close_reason), ('closed', 'fixed')); self.assertIsNotNone(bug.closed_at)
        self.assertEqual([h.new_value for h in bug.history.order_by('id') if h.field == 'status'],
                         ['In progress', 'Fixed', 'Retest', 'Closed (Fixed)'])

    def test_developer_cannot_close(self):
        bug = self.make_bug(status='fixed')
        self.status(bug, 'closed', self.dev, reason='fixed'); bug.refresh_from_db()
        self.assertEqual(bug.status, 'fixed')

    def test_close_without_fix_needs_a_real_reason(self):
        bug = self.make_bug()
        r = self.status(bug, 'closed', self.qa); self.assertContains(r, 'Choose why'); bug.refresh_from_db(); self.assertEqual(bug.status, 'open')
        self.status(bug, 'closed', self.qa, reason='fixed'); bug.refresh_from_db(); self.assertEqual(bug.status, 'open')   # 'fixed' is not valid here
        self.status(bug, 'closed', self.mgr, reason='not_a_bug'); bug.refresh_from_db()
        self.assertEqual((bug.status, bug.close_reason), ('closed', 'not_a_bug'))

    def test_failed_retest_reopens_and_counts(self):
        bug = self.make_bug(status='retest')
        self.status(bug, 'reopened', self.qa); self.status(bug, 'in_progress', self.dev); self.status(bug, 'fixed', self.dev)
        self.status(bug, 'reopened', self.qa); bug.refresh_from_db()
        self.assertEqual((bug.status, bug.reopen_count), ('reopened', 2))

    def test_reopen_clears_close_info(self):
        bug = self.make_bug(status='closed', close_reason='deferred')
        self.status(bug, 'reopened', self.qa); bug.refresh_from_db()
        self.assertEqual((bug.status, bug.close_reason, bug.closed_at), ('reopened', '', None))

    def test_illegal_jump_refused(self):
        bug = self.make_bug()
        self.status(bug, 'fixed', self.mgr); bug.refresh_from_db(); self.assertEqual(bug.status, 'open')

    def test_stale_page_cannot_overwrite_newer_status(self):
        bug = self.make_bug()
        self.status(bug, 'in_progress', self.dev)                       # dev moves it first
        r = self.status(bug, 'closed', self.qa, reason='duplicate', seen='open')   # QA acted on the old page
        self.assertContains(r, 'Someone changed this bug'); bug.refresh_from_db(); self.assertEqual(bug.status, 'in_progress')

    # ---- editing, comments, assignment ----
    def test_edit_logs_only_changed_fields(self):
        bug = self.make_bug(severity='major')
        r = self.client.get(self.u('bug_edit', bug.pk)); version = r.context['version']
        self.client.post(self.u('bug_edit', bug.pk), {**self.body(severity='critical', title=bug.title), 'version': version})
        bug.refresh_from_db(); self.assertEqual(bug.severity, 'critical')
        changed = {h.field: (h.old_value, h.new_value) for h in bug.history.all()}
        self.assertEqual(changed['severity'], ('Major', 'Critical')); self.assertNotIn('title', changed)

    def test_stale_edit_is_refused(self):
        bug = self.make_bug()
        version = self.client.get(self.u('bug_edit', bug.pk)).context['version']
        Bug.objects.filter(pk=bug.pk).update(title='Changed by someone else')
        bug.refresh_from_db(); bug.save()                                 # bumps updated_at
        self.client.post(self.u('bug_edit', bug.pk), {**self.body(title='My edit'), 'version': version})
        bug.refresh_from_db(); self.assertEqual(bug.title, 'Changed by someone else')

    def test_developer_cannot_edit_but_can_comment_and_assign(self):
        bug = self.make_bug(); self.client.force_login(self.dev)
        self.assertEqual(self.client.get(self.u('bug_edit', bug.pk)).status_code, 403)
        self.client.post(self.u('bug_comment', bug.pk), {'text': 'Looking into it'})
        self.assertEqual(bug.comments.get().author, self.dev)
        self.client.post(self.u('bug_assign', bug.pk), {'assignee': self.mgr.pk}); bug.refresh_from_db()
        self.assertEqual(bug.assignee, self.mgr); self.assertTrue(bug.history.filter(field='assignee').exists())

    def test_cannot_assign_to_non_member(self):
        outsider = User.objects.create_user('out', password='x'); bug = self.make_bug()
        self.client.post(self.u('bug_assign', bug.pk), {'assignee': outsider.pk}); bug.refresh_from_db()
        self.assertIsNone(bug.assignee)

    def test_non_member_gets_404_and_empty_comment_rejected(self):
        bug = self.make_bug(); outsider = User.objects.create_user('out', password='x', role='manager')
        self.client.force_login(outsider); self.assertEqual(self.client.get(self.u('bug_detail', bug.pk)).status_code, 404)
        self.client.force_login(self.qa); self.client.post(self.u('bug_comment', bug.pk), {'text': '  '})
        self.assertEqual(bug.comments.count(), 0)

    def test_list_filters(self):
        a = self.make_bug(title='Login broken', severity='critical', assignee=self.dev)
        b = self.make_bug(title='Typo', severity='trivial'); c = self.make_bug(title='Old', status='closed')
        def ids(qs): return {x.pk for x in self.client.get(self.u('bug_list') + qs).context['page']}
        self.assertEqual(ids(''), {a.pk, b.pk})                       # closed hidden by default
        self.assertEqual(ids('?status=all'), {a.pk, b.pk, c.pk})
        self.assertEqual(ids('?severity=critical'), {a.pk})
        self.assertEqual(ids('?q=BUG-2'), {b.pk})
        self.client.force_login(self.dev); self.assertEqual(ids('?assignee=me'), {a.pk})
