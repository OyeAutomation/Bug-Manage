from datetime import date

from django import forms


class RunForm(forms.Form):
    name = forms.CharField(max_length=150)
    run_date = forms.DateField(label='Date', initial=date.today, widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    build = forms.CharField(max_length=60, label='Version')
    assigned_qa = forms.ModelChoiceField(queryset=None, label='QA (tester)')
    environment = forms.CharField(max_length=60, required=False, label='Environment (optional)')

    def __init__(self, *args, project, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        testers = project.members.filter(is_active=True, role__in=['qa', 'manager', 'admin'])
        self.fields['assigned_qa'].queryset = testers
        self.fields['assigned_qa'].label_from_instance = lambda u: u.display_name
        if testers.filter(pk=user.pk).exists():
            self.fields['assigned_qa'].initial = user.pk

    def clean(self):
        data = super().clean()
        if not self.project.test_cases.filter(archived=False).exists():
            raise forms.ValidationError('There are no active test cases yet. Add them in the Test cases tab first.')
        return data
