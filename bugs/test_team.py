from django.test import TestCase as DjangoTestCase
from django.urls import reverse

from accounts.models import User
from projects.models import Module, Project, TeamChange
from runs.models import TestResult, TestRun
from testcases.models import TestCase
from testcases.services import clean_row
from .models import Bug


class TeamFlowTests(DjangoTestCase):
    def setUp(self):
        mk = lambda name, role: User.objects.create_user(name, password='x', role=role, first_name=name.title())
        self.qa, self.mgr, self.ba = mk('qa1', 'qa'), mk('mgr', 'manager'), mk('bea', 'ba')
        self.be, self.fe, self.be2 = mk('bob', 'developer'), mk('fay', 'developer'), mk('ben', 'developer')
        self.p = Project.objects.create(name='Shop', backend_dev=self.be, frontend_dev=self.fe, ba=self.ba)
        self.p.members.add(self.qa, self.mgr, self.ba, self.be, self.fe, self.be2)
        self.mod = Module.objects.create(project=self.p, name='Pay')
        self.run = TestRun.objects.create(project=self.p, name='R1', build='1', environment='QA', created_by=self.qa)
        self.client.force_login(self.qa)

    def u(self, name, *a):
        return reverse(name, args=[self.p.pk, *a])

    def fail(self, layer='frontend', title=None, note='', run=None):
        run = run or self.run
        case = TestCase.objects.create(project=self.p, module=self.mod, title=title or f'{layer} case',
                                       steps='s', expected_result='e', layer=layer, created_by=self.qa)
        res = TestResult.objects.create(run=run, test_case=case)
        self.client.post(self.u('run_set_result', run.pk, res.pk), {'result': 'fail', 'note': note})
        return res

    def move(self, bug, target, user, **extra):
        bug.refresh_from_db(); self.client.force_login(user)
        self.client.post(self.u('bug_status', bug.pk), {'target': target, 'seen_status': bug.status, **extra})
        bug.refresh_from_db()

    def change_team(self, **who):
        self.client.force_login(self.mgr)
        return self.client.post(reverse('project_team', args=[self.p.pk]), {k: (v.pk if v else '') for k, v in who.items()})

    # ---- Frontend & Backend ----
    def test_both_layer_everywhere(self):
        data, errors = clean_row({'module': 'm', 'title': 't', 'steps': 's', 'expected_result': 'e', 'layer': 'Frontend & Backend'})
        self.assertEqual((data['layer'], errors), ('both', []))
        res = self.fail('both')
        self.assertEqual(res.bugs.get().layer, 'both')
        body = self.client.get(self.u('cases_export')).content.decode()
        self.assertIn('Frontend & Backend', body)

    # ---- failed case -> bug in Bugs tab, optional actual result ----
    def test_fail_creates_bug_assigned_by_layer(self):
        self.assertEqual(self.fail('backend').bugs.get().assignee, self.be)
        self.assertEqual(self.fail('frontend').bugs.get().assignee, self.fe)
        both = self.fail('both').bugs.get()
        self.assertEqual((both.assignee, both.co_assignee), (self.be, self.fe))

    def test_actual_result_is_optional(self):
        self.assertEqual(self.fail(note='').bugs.get().actual_result, '')
        self.assertEqual(self.fail(note='boom').bugs.get().actual_result, 'boom')

    def test_both_layer_with_only_one_developer(self):
        self.p.backend_dev = None; self.p.save()
        bug = self.fail('both').bugs.get()
        self.assertEqual((bug.assignee, bug.co_assignee), (self.fe, None))

    def test_no_developer_for_layer_leaves_bug_unassigned(self):
        self.p.frontend_dev = None; self.p.save()
        self.assertIsNone(self.fail('frontend').bugs.get().assignee)

    def test_failing_same_result_twice_makes_one_bug(self):
        res = self.fail()
        self.client.post(self.u('run_set_result', self.run.pk, res.pk), {'result': 'fail'})
        self.assertEqual(Bug.objects.count(), 1)

    def test_open_bug_for_same_case_gets_a_note_not_a_duplicate(self):
        res = self.fail(title='Same case')
        run2 = TestRun.objects.create(project=self.p, name='R2', build='2', created_by=self.qa)
        res2 = TestResult.objects.create(run=run2, test_case=res.test_case)
        self.client.post(self.u('run_set_result', run2.pk, res2.pk), {'result': 'fail', 'note': 'still broken'})
        bug = Bug.objects.get()
        self.assertIn('Failed again in run "R2"', bug.comments.get().text)
        self.assertIn('still broken', bug.comments.get().text)

    # ---- names stay with solved bugs when the team changes ----
    def test_fixed_bug_keeps_original_developer_after_team_change(self):
        old = self.fail('backend').bugs.get()
        self.move(old, 'in_progress', self.be); self.move(old, 'fixed', self.be)
        self.assertEqual((old.solved_by_backend, old.solved_by_frontend), ('Bob', ''))
        self.change_team(backend_dev=self.be2, frontend_dev=self.fe, ba=self.ba)
        old.refresh_from_db()
        self.assertEqual(old.solved_by_backend, 'Bob')                       # history is untouched
        new = self.fail('backend').bugs.get(assignee=self.be2)               # new bugs go to the new developer
        self.move(new, 'in_progress', self.be2); self.move(new, 'fixed', self.be2)
        self.assertEqual(new.solved_by_backend, 'Ben')
        self.assertEqual(self.client.get(self.u('bug_detail', old.pk)).context['fixed_by'], 'Bob (Backend)')

    def test_both_layer_fixed_stamps_both_developers(self):
        bug = self.fail('both').bugs.get()
        self.move(bug, 'in_progress', self.be); self.move(bug, 'fixed', self.fe)
        self.assertEqual((bug.solved_by_backend, bug.solved_by_frontend), ('Bob', 'Fay'))

    def test_team_change_moves_only_unfixed_bugs(self):
        open_bug = self.fail('backend').bugs.get(); fixed = self.fail('backend', title='other').bugs.get()
        self.move(fixed, 'in_progress', self.be); self.move(fixed, 'fixed', self.be)
        r = self.change_team(backend_dev=self.be2, frontend_dev=self.fe, ba=self.ba)
        open_bug.refresh_from_db(); fixed.refresh_from_db()
        self.assertEqual((open_bug.assignee, fixed.assignee), (self.be2, self.be))
        self.assertTrue(open_bug.history.filter(field='assignee', old_value='Bob', new_value='Ben').exists())

    def test_manually_assigned_bug_is_not_moved_by_team_change(self):
        bug = self.fail('backend').bugs.get()
        self.client.post(self.u('bug_assign', bug.pk), {'assignee': self.fe.pk})     # someone chose Fay on purpose
        self.change_team(backend_dev=self.be2, frontend_dev=self.fe, ba=self.ba)
        bug.refresh_from_db(); self.assertEqual(bug.assignee, self.fe)

    # ---- team page ----
    def test_only_leads_edit_team_and_changes_are_logged(self):
        self.client.force_login(self.qa)
        self.assertEqual(self.client.get(reverse('project_team', args=[self.p.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('project_team', args=[self.p.pk]), {}).status_code, 403)
        self.change_team(backend_dev=self.be2, frontend_dev=self.fe, ba=None)
        self.p.refresh_from_db()
        self.assertEqual((self.p.backend_dev, self.p.ba), (self.be2, None))
        log = {(c.role, c.old_name, c.new_name) for c in TeamChange.objects.all()}
        self.assertEqual(log, {('backend', 'Bob', 'Ben'), ('ba', 'Bea', '')})

    def test_team_picks_need_the_right_role_but_not_prior_membership(self):
        self.change_team(backend_dev=self.qa, frontend_dev=self.fe, ba=self.ba)        # a tester is not a developer
        self.change_team(backend_dev=self.be, frontend_dev=self.fe, ba=self.be)        # a developer cannot be the BA
        self.p.refresh_from_db(); self.assertEqual((self.p.backend_dev, self.p.ba), (self.be, self.ba))
        self.assertEqual(TeamChange.objects.count(), 0)

    def test_developer_created_in_admin_can_be_picked_and_joins_the_project(self):
        new_dev = User.objects.create_user('newdev', password='x', role='developer', first_name='Nina')   # not a member yet
        page = self.client.force_login(self.mgr) or self.client.get(reverse('project_team', args=[self.p.pk]))
        self.assertIn(new_dev, page.context['form'].fields['backend_dev'].queryset)
        self.change_team(backend_dev=new_dev, frontend_dev=self.fe, ba=self.ba)
        self.p.refresh_from_db()
        self.assertEqual(self.p.backend_dev, new_dev); self.assertTrue(self.p.members.filter(pk=new_dev.pk).exists())
        # ...and from now on they show up where bugs are assigned
        bug = self.fail('backend').bugs.get()
        self.assertEqual(bug.assignee, new_dev)
        self.client.force_login(self.qa)
        self.assertIn(new_dev, self.client.get(self.u('bug_detail', bug.pk)).context['members'])

    def test_wrong_role_and_inactive_users_are_not_offered(self):
        tester = User.objects.create_user('t2', password='x', role='qa')
        gone = User.objects.create_user('gone', password='x', role='developer', is_active=False)
        self.client.force_login(self.mgr)
        offered = self.client.get(reverse('project_team', args=[self.p.pk])).context['form'].fields['backend_dev'].queryset
        self.assertNotIn(tester, offered); self.assertNotIn(gone, offered)

    def test_team_page_explains_when_no_developer_exists(self):
        User.objects.filter(role='developer').delete(); self.client.force_login(self.mgr)
        self.assertContains(self.client.get(reverse('project_team', args=[self.p.pk])), 'No active user has the role Developer')

    # ---- not required (BA decision) ----
    def test_not_required_needs_a_ba_and_records_the_name(self):
        bug = self.fail().bugs.get()
        self.p.ba = None; self.p.save()
        self.client.force_login(self.qa); self.client.post(self.u('bug_status', bug.pk), {'quick': 'not_required', 'seen_status': 'open'})
        bug.refresh_from_db(); self.assertEqual(bug.status, 'open')                      # refused: no BA yet
        self.p.ba = self.ba; self.p.save()
        self.client.post(self.u('bug_status', bug.pk), {'quick': 'not_required', 'seen_status': 'open'})
        bug.refresh_from_db()
        self.assertEqual((bug.status, bug.close_reason, bug.ba_name), ('closed', 'not_required', 'Bea'))

    def test_manager_can_mark_not_required_developer_cannot(self):
        bug = self.fail().bugs.get()
        self.client.force_login(self.fe); self.client.post(self.u('bug_status', bug.pk), {'quick': 'not_required', 'seen_status': 'open'})
        bug.refresh_from_db(); self.assertEqual(bug.status, 'open')
        self.client.force_login(self.mgr); self.client.post(self.u('bug_status', bug.pk), {'quick': 'not_required', 'seen_status': 'open'})
        bug.refresh_from_db(); self.assertEqual(bug.close_reason, 'not_required')

    def test_ba_can_view_and_comment_but_not_change_bugs(self):
        bug = self.fail().bugs.get(); self.client.force_login(self.ba)
        self.assertEqual(self.client.get(self.u('bug_detail', bug.pk)).status_code, 200)
        self.client.post(self.u('bug_comment', bug.pk), {'text': 'Not needed for launch'})
        self.assertEqual(bug.comments.get().author, self.ba)
        self.client.post(self.u('bug_status', bug.pk), {'target': 'closed', 'reason': 'wont_fix', 'seen_status': 'open'})
        bug.refresh_from_db(); self.assertEqual(bug.status, 'open')
        self.assertEqual(self.client.get(self.u('bug_edit', bug.pk)).status_code, 403)

    # ---- misc ----
    def test_my_bugs_filter_includes_second_developer(self):
        both = self.fail('both').bugs.get(); self.client.force_login(self.fe)
        ids = {b.pk for b in self.client.get(self.u('bug_list') + '?assignee=me').context['page']}
        self.assertEqual(ids, {both.pk})

    def test_layer_change_reassigns_when_assignee_untouched(self):
        bug = self.fail('frontend').bugs.get()
        version = self.client.get(self.u('bug_edit', bug.pk)).context['version']
        body = {'title': bug.title, 'module': self.mod.pk, 'steps': 's', 'expected_result': 'e', 'actual_result': '',
                'layer': 'backend', 'severity': 'major', 'priority': 'medium', 'environment': '', 'build': '',
                'assignee': self.fe.pk, 'release_phase': 'qa', 'version': version}
        self.client.post(self.u('bug_edit', bug.pk), body)
        bug.refresh_from_db(); self.assertEqual((bug.layer, bug.assignee), ('backend', self.be))

    def test_tabs_render_on_project_pages(self):
        for name in ('project_detail', 'case_list', 'run_list', 'bug_list'):
            args = [self.p.pk] if name == 'project_detail' else [self.p.pk]
            self.assertContains(self.client.get(reverse(name, args=args)), 'aria-label="Project sections"')


    # ---- developer type: anyone on the project can change it; filter on the Bugs tab ----
    def set_type(self, bug, layer, user):
        self.client.force_login(user)
        self.client.post(self.u('bug_layer', bug.pk), {'layer': layer}); bug.refresh_from_db()

    def test_every_role_on_the_project_can_change_developer_type(self):
        for who in (self.be, self.ba, self.qa, self.mgr):
            self.client.force_login(self.qa)          # the tester runs the case; then each role changes its type
            bug = self.fail('frontend').bugs.get(); self.set_type(bug, 'backend', who)
            self.assertEqual(bug.layer, 'backend', who.role); Bug.objects.all().delete()

    def test_changing_type_moves_unfixed_bug_to_matching_developers_and_logs_it(self):
        bug = self.fail('frontend').bugs.get(); self.assertEqual(bug.assignee, self.fe)
        self.set_type(bug, 'both', self.be)
        self.assertEqual((bug.layer, bug.assignee, bug.co_assignee), ('both', self.be, self.fe))
        self.set_type(bug, 'backend', self.fe)
        self.assertEqual((bug.assignee, bug.co_assignee), (self.be, None))
        entry = bug.history.filter(field='layer').first()
        self.assertEqual((entry.old_value, entry.new_value, entry.field_label), ('Frontend & Backend', 'Backend', 'developer type'))

    def test_manual_assignment_is_kept_when_type_changes(self):
        bug = self.fail('frontend').bugs.get()
        self.client.post(self.u('bug_assign', bug.pk), {'assignee': self.be2.pk})
        self.set_type(bug, 'backend', self.qa); self.assertEqual(bug.assignee, self.be2)

    def test_fixed_bug_keeps_its_names_when_type_changes_later(self):
        bug = self.fail('backend').bugs.get()
        self.move(bug, 'in_progress', self.be); self.move(bug, 'fixed', self.be)
        self.set_type(bug, 'frontend', self.qa)
        self.assertEqual((bug.layer, bug.assignee, bug.solved_by_backend, bug.solved_by_frontend), ('frontend', self.be, 'Bob', ''))

    def test_invalid_type_and_non_members_are_refused(self):
        bug = self.fail('frontend').bugs.get(); self.set_type(bug, 'nonsense', self.qa); self.assertEqual(bug.layer, 'frontend')
        outsider = User.objects.create_user('out', password='x', role='developer'); self.client.force_login(outsider)
        self.assertEqual(self.client.post(self.u('bug_layer', bug.pk), {'layer': 'backend'}).status_code, 404)

    def test_bug_page_shows_the_developer_type_control_to_a_developer(self):
        bug = self.fail('frontend').bugs.get(); self.client.force_login(self.fe)
        self.assertContains(self.client.get(self.u('bug_detail', bug.pk)), 'aria-label="Developer type"')

    def test_bugs_tab_filters_by_developer_type(self):
        a = self.fail('backend').bugs.get(); b = self.fail('frontend').bugs.get(); c = self.fail('both').bugs.get()
        self.client.force_login(self.fe)
        ids = lambda qs: {x.pk for x in self.client.get(self.u('bug_list') + qs).context['page']}
        self.assertEqual(ids('?layer=backend'), {a.pk}); self.assertEqual(ids('?layer=frontend'), {b.pk})
        self.assertEqual(ids('?layer=both'), {c.pk}); self.assertEqual(ids(''), {a.pk, b.pk, c.pk})
        page = self.client.get(self.u('bug_list') + '?layer=both')
        self.assertContains(page, 'name="layer"'); self.assertContains(page, 'Frontend &amp; Backend')
