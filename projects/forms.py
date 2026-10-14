from django import forms
from accounts.models import User
from .models import Project, Module, SubModule


class _MemberChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, user):
        return f'{user.display_name} ({user.get_role_display()})'      # the role is shown so mistakes are easy to spot


class ProjectForm(forms.ModelForm):
    members = _MemberChoice(
        queryset=User.objects.filter(is_active=True).order_by('role', 'username'), required=False,
        widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Project
        fields = ['name', 'description', 'members']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}


class ModuleForm(forms.ModelForm):
    class Meta:
        model = Module
        fields = ['name']


class SubModuleForm(forms.ModelForm):
    class Meta:
        model = SubModule
        fields = ['name']


class _PersonChoice(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return user.display_name


class TeamForm(forms.ModelForm):
    backend_dev = _PersonChoice(queryset=User.objects.none(), required=False, label='Backend developer')
    frontend_dev = _PersonChoice(queryset=User.objects.none(), required=False, label='Frontend developer')
    ba = _PersonChoice(queryset=User.objects.none(), required=False, label='Business analyst (BA)')

    class Meta:
        model = Project
        fields = ['backend_dev', 'frontend_dev', 'ba']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Anyone with the right role can be picked. Picking them also adds them to the project (see the view).
        developers = User.objects.filter(is_active=True, role='developer')
        self.fields['backend_dev'].queryset = developers
        self.fields['frontend_dev'].queryset = developers
        self.fields['ba'].queryset = User.objects.filter(is_active=True, role='ba')
