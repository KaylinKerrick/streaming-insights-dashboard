"""
Analytics service for the Streaming Insights dashboard.

Each public function queries the database using Django ORM aggregation and
returns plain Python dicts / lists suitable for JSON serialisation and
Chart.js rendering.  Decimal values are converted to float before returning
so the caller never needs a custom JSON encoder.

One function (average_ratings_by_platform_raw_sql) demonstrates the same
query written as parameterised raw SQL — see the docstring for the rationale.
"""

from django.db import connection
from django.db.models import Avg, Count, Q

from dashboard.models import Content, Genre, Platform


# ── Homepage summary ───────────────────────────────────────────────────────────

def summary_stats() -> dict:
    """
    Aggregate numbers for the four homepage stat cards.

    Returns
    -------
    dict with keys:
        total_titles    int   – distinct Content records
        total_platforms int   – Platform records in the database
        total_genres    int   – Genre records in the database
        avg_rating      float – mean tmdb_rating across rated titles, or None
        rated_count     int   – number of titles that have a rating
    """
    total_titles    = Content.objects.count()
    total_platforms = Platform.objects.count()
    total_genres    = Genre.objects.count()

    agg = (
        Content.objects
        .filter(tmdb_rating__isnull=False)
        .aggregate(avg=Avg('tmdb_rating'), rated=Count('id'))
    )
    avg_raw = agg['avg']

    return {
        'total_titles':    total_titles,
        'total_platforms': total_platforms,
        'total_genres':    total_genres,
        'avg_rating':      round(float(avg_raw), 1) if avg_raw is not None else None,
        'rated_count':     agg['rated'],
    }


# ── Chart A: catalog size by platform ─────────────────────────────────────────

def catalog_size_by_platform() -> list:
    """
    Count of distinct Content titles associated with each Platform.

    distinct=True prevents double-counting a title that has more than one
    ContentPlatform row for the same platform (e.g. different regions).

    Returns
    -------
    list of {'name': str, 'count': int}, ordered by count descending.
    Only platforms with at least one associated title are included.
    """
    rows = (
        Platform.objects
        .annotate(count=Count('content_links__content', distinct=True))
        .filter(count__gt=0)
        .order_by('-count')
        .values('name', 'count')
    )
    return list(rows)


# ── Chart B: genre distribution ───────────────────────────────────────────────

def genre_distribution(
    platform_id: int = None,
    content_type: str = None,
    year_from: int = None,
) -> list:
    """
    Count of titles per genre, with optional filters.

    Because a title can belong to multiple genres, the sum of all genre counts
    will exceed the total number of unique titles — this is expected and should
    be noted wherever these numbers are displayed.

    Parameters
    ----------
    platform_id  : filter to titles associated with this Platform id
    content_type : filter to 'movie' or 'tv'
    year_from    : only count titles with release_year >= this value

    Returns
    -------
    list of {'name': str, 'count': int}, ordered by count descending.
    """
    filters = Q()
    if content_type:
        filters &= Q(content__content_type=content_type)
    if platform_id:
        filters &= Q(content__platform_links__platform_id=platform_id)
    if year_from:
        filters &= Q(content__release_year__gte=year_from)

    rows = (
        Genre.objects
        .annotate(count=Count('content', filter=filters, distinct=True))
        .filter(count__gt=0)
        .order_by('-count')
        .values('name', 'count')
    )
    return list(rows)


# ── Chart C: average rating by platform ───────────────────────────────────────

def average_ratings_by_platform() -> list:
    """
    Mean TMDB rating for content on each platform, excluding unrated titles.

    avg_rating is rounded to 2 decimal places and returned as float.
    rated_count tells the caller how many titles the average is based on —
    always display this alongside the average to convey sample size.

    Returns
    -------
    list of {'name': str, 'avg_rating': float, 'rated_count': int},
    ordered by avg_rating descending.
    """
    rows = (
        Platform.objects
        .annotate(
            avg_rating=Avg(
                'content_links__content__tmdb_rating',
                filter=Q(content_links__content__tmdb_rating__isnull=False),
            ),
            rated_count=Count(
                'content_links__content',
                filter=Q(content_links__content__tmdb_rating__isnull=False),
                distinct=True,
            ),
        )
        .filter(rated_count__gt=0)
        .order_by('-avg_rating')
        .values('name', 'avg_rating', 'rated_count')
    )
    return [
        {
            'name':        row['name'],
            'avg_rating':  round(float(row['avg_rating']), 2),
            'rated_count': row['rated_count'],
        }
        for row in rows
    ]


# ── Chart D: titles by release year ───────────────────────────────────────────

def content_by_release_year(
    platform_id: int = None,
    genre_slug: str = None,
    content_type: str = None,
) -> list:
    """
    Count of titles released per year, with optional filters.
    Titles without a release_year are excluded.

    Returns
    -------
    list of {'year': int, 'count': int}, ordered by year ascending.
    """
    qs = Content.objects.filter(release_year__isnull=False)

    if content_type:
        qs = qs.filter(content_type=content_type)
    if platform_id:
        qs = qs.filter(platform_links__platform_id=platform_id).distinct()
    if genre_slug:
        qs = qs.filter(genres__slug=genre_slug).distinct()

    rows = (
        qs
        .values('release_year')
        .annotate(count=Count('id'))
        .order_by('release_year')
    )
    return [{'year': r['release_year'], 'count': r['count']} for r in rows]


# ── Highest-rated content (used by Insights page in Milestone 7) ──────────────

def highest_rated_content(
    genre_slug: str = None,
    content_type: str = None,
    platform_id: int = None,
    min_votes: int = 5,
    limit: int = 10,
):
    """
    Content ordered by tmdb_rating descending.

    min_votes filters out titles rated by very few users, reducing the
    influence of statistical outliers.  The default of 5 is intentionally
    low for the sample dataset; raise it when using a larger dataset.

    Returns a QuerySet of Content objects with genres and platforms
    prefetched for efficient template rendering.
    """
    qs = (
        Content.objects
        .filter(tmdb_rating__isnull=False, tmdb_vote_count__gte=min_votes)
        .prefetch_related('genres', 'platforms')
    )
    if content_type:
        qs = qs.filter(content_type=content_type)
    if platform_id:
        qs = qs.filter(platform_links__platform_id=platform_id).distinct()
    if genre_slug:
        qs = qs.filter(genres__slug=genre_slug).distinct()

    return qs.order_by('-tmdb_rating', 'title')[:limit]


# ── Platform comparison (used by Compare page in Milestone 7) ─────────────────

def platform_comparison(platform1_id: int, platform2_id: int) -> dict:
    """
    Side-by-side metrics for two platforms.

    All counts use distinct Content records via ContentPlatform.
    Data reflects the imported dataset — not verified current catalogs.

    Returns
    -------
    dict keyed by platform id, each value containing:
        platform, total, movies, tv_shows, avg_rating, rated_count
    """
    platforms = Platform.objects.filter(id__in=[platform1_id, platform2_id])
    result = {}

    for p in platforms:
        qs      = Content.objects.filter(platform_links__platform=p)
        rated   = qs.filter(tmdb_rating__isnull=False)
        avg_raw = rated.aggregate(avg=Avg('tmdb_rating'))['avg']

        result[p.id] = {
            'platform':    p,
            'total':       qs.count(),
            'movies':      qs.filter(content_type=Content.MOVIE).count(),
            'tv_shows':    qs.filter(content_type=Content.TV).count(),
            'avg_rating':  round(float(avg_raw), 2) if avg_raw is not None else None,
            'rated_count': rated.count(),
        }

    return result


# ── Raw SQL example ────────────────────────────────────────────────────────────

def average_ratings_by_platform_raw_sql(min_titles: int = 0) -> list:
    """
    Identical result to average_ratings_by_platform(), implemented as raw SQL.

    Why raw SQL here?
        This query joins three tables (platform → contentplatform → content)
        and uses both HAVING and ROUND(), which the ORM expresses less
        transparently.  The raw version is included to demonstrate that the
        underlying SQL is understood — not to replace ORM usage elsewhere.

    Security: min_titles is passed as a parameterised %s placeholder.
    Table and column names are from the application's own schema and are
    never derived from user input.

    Returns
    -------
    list of {'platform_name': str, 'avg_rating': Decimal, 'rated_count': int}
    """
    sql = """
        SELECT
            p.name                        AS platform_name,
            ROUND(AVG(c.tmdb_rating), 2)  AS avg_rating,
            COUNT(DISTINCT c.id)          AS rated_count
        FROM dashboard_platform p
        INNER JOIN dashboard_contentplatform cp ON cp.platform_id = p.id
        INNER JOIN dashboard_content c          ON c.id = cp.content_id
        WHERE c.tmdb_rating IS NOT NULL
        GROUP BY p.id, p.name
        HAVING COUNT(DISTINCT c.id) > %s
        ORDER BY avg_rating DESC
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [min_titles])
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
