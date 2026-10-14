"""Who may do what, in one place."""
EDITORS = ('admin', 'manager', 'qa')        # write test cases, run tests, raise and edit bugs
CASE_EDITORS = EDITORS + ('ba',)         # also the business analyst: add, edit, delete test cases; create runs
LEADS = ('admin', 'manager')                # reopen closed runs, close bugs without a fix, etc.
