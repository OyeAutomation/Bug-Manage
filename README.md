# QA Tracker (Phase 4.4: project team, test cases, Excel import, test runs with skip-to-end, auto-created bugs)

## After unzipping an update: run  python manage.py migrate  FIRST (keeps your data, adds new columns)

## First-time setup
    python -m venv .venv
    .venv\Scripts\activate          (Windows)   |   source .venv/bin/activate   (Linux/macOS)
    pip install -r requirements.txt     # Django, openpyxl, defusedxml
    python manage.py migrate
    python manage.py createsuperuser

## Run (everyone on the LAN can open http://<this-pc-ip>:8000)
    python manage.py runserver 0.0.0.0:8000

## Other commands
    python manage.py test      # run automated tests
    python manage.py backup    # zip of database + media in backups/

Create users and set their Role in the Admin panel (/admin/), then create a project and add members.
