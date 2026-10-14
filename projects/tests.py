from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from .models import Module, Project


class ProjectAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', password='x')
        self.manager = User.objects.create_user('mgr', password='x', role='manager')
        self.qa = User.objects.create_user('qa1', password='x', role='qa')
        self.dev = User.objects.create_user('dev1', password='x', role='developer')
        self.project = Project.objects.create(name='Checkout')
        self.project.members.add(self.qa, self.dev)

    def test_superuser_is_admin_role(self):
        self.assertEqual(self.admin.role, 'admin')

    def test_login_required(self):
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 302)

    def test_non_member_cannot_see_project(self):
        self.client.force_login(self.manager)  # manager, but not a member
        r = self.client.get(reverse('project_detail', args=[self.project.pk]))
        self.assertEqual(r.status_code, 404)

    def test_admin_sees_all_projects(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('project_detail', args=[self.project.pk]))
        self.assertEqual(r.status_code, 200)

    def test_only_admin_or_manager_creates_projects(self):
        self.client.force_login(self.qa)
        self.assertEqual(self.client.get(reverse('project_create')).status_code, 403)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('project_create')).status_code, 200)

    def test_qa_adds_module_developer_cannot(self):
        url = reverse('module_add', args=[self.project.pk])
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(url, {'name': 'Cart'}).status_code, 403)
        self.client.force_login(self.qa)
        self.client.post(url, {'name': 'Cart'})
        self.assertTrue(Module.objects.filter(project=self.project, name='Cart').exists())

    def test_duplicate_module_rejected(self):
        self.client.force_login(self.qa)
        url = reverse('module_add', args=[self.project.pk])
        self.client.post(url, {'name': 'Cart'}); self.client.post(url, {'name': 'Cart'})
        self.assertEqual(Module.objects.filter(project=self.project, name='Cart').count(), 1)

    def test_theme_toggle_saves(self):
        self.client.force_login(self.qa)
        self.client.post(reverse('toggle_theme'), {'next': '/'})
        self.qa.refresh_from_db()
        self.assertEqual(self.qa.theme, 'dark')
