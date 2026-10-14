from django.apps import AppConfig
from django.db.backends.signals import connection_created


def enable_wal(sender, connection, **kwargs):
    """Runs every time a SQLite connection opens. WAL lets readers and a writer work at once."""
    if connection.vendor == 'sqlite':
        cur = connection.cursor()
        cur.execute('PRAGMA journal_mode=WAL;')
        cur.execute('PRAGMA synchronous=NORMAL;')
        cur.execute('PRAGMA busy_timeout=5000;')  # wait up to 5s instead of failing when busy


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        connection_created.connect(enable_wal)
