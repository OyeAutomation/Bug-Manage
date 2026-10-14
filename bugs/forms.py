from django import forms

from accounts.models import User
from projects.models import SubModule
from .models import Bug


class MemberChoice(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return f'{user.display_name} ({user.get_role_display()})'


class BugForm(forms.ModelForm):
    assignee = MemberChoice(queryset=User.objects.none(), required=False)

    class Meta:
        model = Bug
        fields = ['title', 'module', 'sub_module', 'steps', 'expected_result', 'actual_result', 'layer',
                  'severity', 'priority', 'environment', 'build', 'assignee', 'release_phase']
        widgets = {'steps': forms.Textarea(attrs={'rows': 4}), 'expected_result': forms.Textarea(attrs={'rows': 2}),
                   'actual_result': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['module'].queryset = project.modules.filter(archived=False)
        self.fields['sub_module'].queryset = SubModule.objects.filter(module__project=project, archived=False)
        self.fields['sub_module'].required = False
        self.fields['assignee'].queryset = project.members.filter(is_active=True)

    def clean(self):
        data = super().clean()
        module, sub = data.get('module'), data.get('sub_module')
        if module and sub and sub.module_id != module.id:
            self.add_error('sub_module', 'This sub-module does not belong to the chosen module.')
        return data
