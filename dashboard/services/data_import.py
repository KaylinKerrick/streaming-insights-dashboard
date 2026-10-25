"""
CSV import service for Content, Genre, and ContentPlatform records.

Entry point: import_csv(filepath, update_existing, stdout) -> ImportStats

CSV format
----------
Required columns : title, content_type
Optional columns : release_year, genres, overview, tmdb_id, tmdb_rating,
                   tmdb_vote_count, poster_path, platforms

Multi-value fields (genres, platforms) use a pipe character as separator:
  genres   = "Action|Drama|Thriller"
  platforms = "Netflix|Hulu"

content_type accepts: movie / tv  (case-insensitive; "TV Show" also accepted)

Deduplication strategy
----------------------
If tmdb_id is present it is the authoritative unique key.
Otherwise (title, content_type, release_year) is used as a natural key —
note this cannot guarantee uniqueness for films with identical names and years.

Idempotency
-----------
Running the same file twice with the default settings updates existing records
in place. Pass update_existing=False to skip records that already exist.
"""

import csv
import decimal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from django.db import transaction
from django.utils.text import slugify

from dashboard.models import Content, ContentPlatform, Genre, Platform


REQUIRED_COLUMNS = {'title', 'content_type'}

# Maps flexible user-supplied strings to canonical model values.
_CONTENT_TYPE_MAP = {
    'movie': Content.MOVIE, 'movies': Content.MOVIE, 'film': Content.MOVIE,
    'tv': Content.TV, 'tvshow': Content.TV, 'tvshows': Content.TV,
    'television': Content.TV, 'series': Content.TV, 'show': Content.TV,
}


# ── Result container ───────────────────────────────────────────────────────────

@dataclass
class ImportStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    rejected: int = 0
    errors: list = field(default_factory=list)  # list of (row_num, message)


# ── Field parsers ──────────────────────────────────────────────────────────────

def _normalize_content_type(value: str) -> Optional[str]:
    """Return 'movie' or 'tv', or None if the value is unrecognisable."""
    key = value.strip().lower().replace(' ', '').replace('_', '').replace('-', '')
    return _CONTENT_TYPE_MAP.get(key)


def _parse_year(value: str) -> Optional[int]:
    """Accept '2001' or '2001-07-20'; return int year or None."""
    val = value.strip()
    if not val:
        return None
    candidate = val[:4]
    if candidate.isdigit():
        year = int(candidate)
        if 1888 <= year <= 2100:
            return year
    return None


def _parse_decimal(value: str, lo: float = 0, hi: float = 10) -> Optional[decimal.Decimal]:
    """Return a Decimal within [lo, hi], or None if missing or out of range."""
    val = value.strip()
    if not val:
        return None
    try:
        d = decimal.Decimal(val)
        return d if lo <= d <= hi else None
    except decimal.InvalidOperation:
        return None


def _parse_nonneg_int(value: str) -> Optional[int]:
    """Return a non-negative int, or None."""
    val = value.strip()
    if not val:
        return None
    try:
        n = int(val)
        return n if n >= 0 else None
    except ValueError:
        return None


def _parse_positive_int(value: str) -> Optional[int]:
    """Return a positive int (> 0), or None — used for tmdb_id."""
    n = _parse_nonneg_int(value)
    return n if n and n > 0 else None


# ── Object resolution ──────────────────────────────────────────────────────────

def _get_or_create_genres(pipe_string: str) -> list:
    """Split a pipe-separated genre string and return Genre objects."""
    genres = []
    for raw in pipe_string.split('|'):
        name = raw.strip().title()   # "action" -> "Action"
        if not name:
            continue
        genre, _ = Genre.objects.get_or_create(
            name=name,
            defaults={'slug': slugify(name)},
        )
        genres.append(genre)
    return genres


def _resolve_platforms(pipe_string: str) -> tuple:
    """
    Match pipe-separated platform names against the database (case-insensitive).
    Returns (matched: list[Platform], unknown: list[str]).
    """
    if not pipe_string.strip():
        return [], []

    platform_map = {p.name.lower(): p for p in Platform.objects.all()}
    matched, unknown = [], []
    for raw in pipe_string.split('|'):
        name = raw.strip()
        if not name:
            continue
        platform = platform_map.get(name.lower())
        if platform:
            matched.append(platform)
        else:
            unknown.append(name)
    return matched, unknown


# ── Per-row logic ──────────────────────────────────────────────────────────────

def _process_row(row: dict, update_existing: bool) -> tuple:
    """
    Validate and import one CSV row. Runs inside a savepoint.
    Returns (action, warning_message).
    action ∈ {'created', 'updated', 'skipped', 'rejected'}.
    """
    # ── Required fields ──
    title = row.get('title', '').strip()
    if not title:
        return 'rejected', 'Missing title'

    raw_ct = row.get('content_type', '')
    content_type = _normalize_content_type(raw_ct)
    if content_type is None:
        return 'rejected', (
            f'Unrecognised content_type "{raw_ct}". '
            f'Expected "movie" or "tv".'
        )

    # ── Optional fields ──
    release_year   = _parse_year(row.get('release_year', ''))
    overview       = row.get('overview', '').strip() or None
    tmdb_id        = _parse_positive_int(row.get('tmdb_id', ''))
    tmdb_rating    = _parse_decimal(row.get('tmdb_rating', ''), 0, 10)
    tmdb_vote_count = _parse_nonneg_int(row.get('tmdb_vote_count', ''))
    poster_path    = row.get('poster_path', '').strip() or None

    field_values = dict(
        title=title,
        content_type=content_type,
        release_year=release_year,
        overview=overview,
        tmdb_rating=tmdb_rating,
        tmdb_vote_count=tmdb_vote_count,
        poster_path=poster_path,
    )
    if tmdb_id:
        field_values['tmdb_id'] = tmdb_id

    # ── Deduplication key ──
    if tmdb_id:
        lookup = {'tmdb_id': tmdb_id}
    else:
        lookup = {
            'title': title,
            'content_type': content_type,
            'release_year': release_year,
        }

    content, created = Content.objects.get_or_create(**lookup, defaults=field_values)

    if not created:
        if not update_existing:
            return 'skipped', ''
        for attr, val in field_values.items():
            setattr(content, attr, val)
        content.save()

    # ── Genres ──
    genres = _get_or_create_genres(row.get('genres', ''))
    content.genres.set(genres)

    # ── Platforms ──
    platforms, unknown = _resolve_platforms(row.get('platforms', ''))
    for platform in platforms:
        ContentPlatform.objects.get_or_create(
            content=content,
            platform=platform,
            region='',
            defaults={'source': 'csv_import'},
        )

    warnings = []
    if unknown:
        warnings.append(f'unrecognised platforms skipped: {", ".join(unknown)}')

    action = 'created' if created else 'updated'
    return action, '; '.join(warnings)


# ── Public entry point ─────────────────────────────────────────────────────────

def import_csv(filepath: str, update_existing: bool = True, stdout=None) -> ImportStats:
    """
    Import Content records from a CSV file.

    Parameters
    ----------
    filepath        : path to the CSV file
    update_existing : when True (default), existing records are updated in-place;
                      when False, they are counted as skipped
    stdout          : optional writable object for progress messages

    Returns an ImportStats instance with row counts and any error details.
    """
    stats = ImportStats()
    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(f'CSV file not found: {filepath}')

    with open(path, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)

        # Validate header row before reading any data rows.
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(
                f'CSV is missing required column(s): {", ".join(sorted(missing))}'
            )

        for row_num, row in enumerate(reader, start=2):
            try:
                with transaction.atomic():
                    action, warning = _process_row(row, update_existing)
            except Exception as exc:
                action, warning = 'rejected', str(exc)

            if action == 'created':
                stats.created += 1
            elif action == 'updated':
                stats.updated += 1
            elif action == 'skipped':
                stats.skipped += 1
            else:  # rejected
                stats.rejected += 1
                label = row.get('title') or '(no title)'
                stats.errors.append((row_num, f'{label} — {warning}'))

            processed = stats.created + stats.updated
            if stdout and processed and processed % 50 == 0:
                stdout.write(f'  … {processed} records imported so far')

    return stats
