import shutil
import sqlite3
import zipfile
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Back up the database and uploaded media into one zip in the backups folder.'

    def handle(self, *args, **options):
        backup_dir = settings.BACKUP_DIR
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        db_copy = backup_dir / f'db-{stamp}.sqlite3'

        # SQLite's own backup API gives a consistent copy even while people are using the app.
        src = sqlite3.connect(settings.DATABASES['default']['NAME'])
        dst = sqlite3.connect(db_copy)
        with dst:
            src.backup(dst)
        src.close(); dst.close()

        archive = backup_dir / f'backup-{stamp}.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(db_copy, 'db.sqlite3')
            media = settings.MEDIA_ROOT
            if media.exists():
                for f in media.rglob('*'):
                    if f.is_file():
                        z.write(f, f'media/{f.relative_to(media)}')
        db_copy.unlink()
        self.stdout.write(self.style.SUCCESS(f'Backup written to {archive}'))
