from django.core.management.base import BaseCommand, CommandError

from dashboard.services.data_import import import_csv


class Command(BaseCommand):
    help = 'Import movie/TV content from a CSV file into the database.'

    def add_arguments(self, parser):
        parser.add_argument(
            'csv_file',
            type=str,
            help='Path to the CSV file (relative or absolute)',
        )
        parser.add_argument(
            '--no-update',
            action='store_true',
            default=False,
            help='Skip records that already exist instead of updating them.',
        )

    def handle(self, *args, **options):
        filepath = options['csv_file']
        update_existing = not options['no_update']

        self.stdout.write(f'Importing: {filepath}')
        mode = 'update existing' if update_existing else 'skip existing'
        self.stdout.write(f'Mode: {mode}')
        self.stdout.write('')

        try:
            stats = import_csv(
                filepath,
                update_existing=update_existing,
                stdout=self.stdout,
            )
        except FileNotFoundError as exc:
            raise CommandError(str(exc))
        except ValueError as exc:
            raise CommandError(str(exc))

        self.stdout.write('--- Results ---')
        self.stdout.write(self.style.SUCCESS(f'  Created  : {stats.created}'))
        self.stdout.write(f'  Updated  : {stats.updated}')
        self.stdout.write(f'  Skipped  : {stats.skipped}')

        if stats.rejected:
            self.stdout.write(self.style.WARNING(f'  Rejected : {stats.rejected}'))
        else:
            self.stdout.write(f'  Rejected : {stats.rejected}')

        if stats.errors:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Rejected rows:'))
            for row_num, msg in stats.errors:
                self.stdout.write(f'  Row {row_num}: {msg}')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Done.'))
