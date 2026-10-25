from django.db import migrations

PLATFORMS = [
    ('Apple TV+',   'apple-tv-plus',  'https://tv.apple.com'),
    ('Disney+',     'disney-plus',    'https://www.disneyplus.com'),
    ('Hulu',        'hulu',           'https://www.hulu.com'),
    ('Max',         'max',            'https://www.max.com'),
    ('Netflix',     'netflix',        'https://www.netflix.com'),
    ('Prime Video', 'prime-video',    'https://www.primevideo.com'),
]


def seed_platforms(apps, schema_editor):
    Platform = apps.get_model('dashboard', 'Platform')
    for name, slug, website in PLATFORMS:
        Platform.objects.get_or_create(slug=slug, defaults={'name': name, 'website': website})


def unseed_platforms(apps, schema_editor):
    Platform = apps.get_model('dashboard', 'Platform')
    slugs = [slug for _, slug, _ in PLATFORMS]
    Platform.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_platforms, reverse_code=unseed_platforms),
    ]
