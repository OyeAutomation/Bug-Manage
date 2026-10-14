from django import forms
from projects.models import SubModule
from .models import TestCase


class TestCaseForm(forms.ModelForm):
    class Meta:
        model = TestCase
        fields = ['module', 'sub_module', 'title', 'steps', 'expected_result', 'layer', 'priority']
        widgets = {'steps': forms.Textarea(attrs={'rows': 5}),
                   'expected_result': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['module'].queryset = project.modules.filter(archived=False)
        self.fields['sub_module'].queryset = SubModule.objects.filter(module__project=project, archived=False)
        self.fields['sub_module'].required = False

    def clean(self):
        data = super().clean()
        module, sub = data.get('module'), data.get('sub_module')
        if module and sub and sub.module_id != module.id:
            self.add_error('sub_module', 'This sub-module does not belong to the chosen module.')
        return data
