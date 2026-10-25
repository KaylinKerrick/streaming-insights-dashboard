from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.shortcuts import get_object_or_404, render

from dashboard.models import Content, Genre, Platform
from dashboard.services import analytics

_SORT_MAP = {
    '-rating': ['-tmdb_rating', 'title'],
    'rating':  ['tmdb_rating',  'title'],
    '-year':   ['-release_year', 'title'],
    'year':    ['release_year',  'title'],
    'title':   ['title'],
    '-title':  ['-title'],
}
_DEFAULT_SORT = '-rating'
ITEMS_PER_PAGE = 12


# ── Homepage ──────────────────────────────────────────────────────────────────

def home(request):
    stats         = analytics.summary_stats()
    platform_data = analytics.catalog_size_by_platform()
    genre_data    = analytics.genre_distribution()
    year_data     = analytics.content_by_release_year()
    rating_data   = analytics.average_ratings_by_platform()

    context = {
        'stats': stats,
        'platform_chart': {
            'labels': [d['name']  for d in platform_data],
            'data':   [d['count'] for d in platform_data],
        },
        'genre_chart': {
            'labels': [d['name']  for d in genre_data],
            'data':   [d['count'] for d in genre_data],
        },
        'year_chart': {
            'labels': [d['year']  for d in year_data],
            'data':   [d['count'] for d in year_data],
        },
        'rating_chart': {
            'labels': [d['name']        for d in rating_data],
            'data':   [d['avg_rating']  for d in rating_data],
            'counts': [d['rated_count'] for d in rating_data],
        },
    }
    return render(request, 'dashboard/home.html', context)


# ── Explore ───────────────────────────────────────────────────────────────────

def explore(request):
    q             = request.GET.get('q', '').strip()
    platform_slug = request.GET.get('platform', '').strip()
    genre_slug    = request.GET.get('genre', '').strip()
    content_type  = request.GET.get('content_type', '').strip()
    year_from     = request.GET.get('year_from', '').strip()
    year_to       = request.GET.get('year_to', '').strip()
    min_rating    = request.GET.get('min_rating', '').strip()
    sort          = request.GET.get('sort', _DEFAULT_SORT)

    if sort not in _SORT_MAP:
        sort = _DEFAULT_SORT

    qs = Content.objects.prefetch_related('genres', 'platforms')

    if q:
        qs = qs.filter(title__icontains=q)
    if platform_slug:
        qs = qs.filter(platform_links__platform__slug=platform_slug).distinct()
    if genre_slug:
        qs = qs.filter(genres__slug=genre_slug).distinct()
    if content_type in (Content.MOVIE, Content.TV):
        qs = qs.filter(content_type=content_type)
    if year_from:
        try:
            qs = qs.filter(release_year__gte=int(year_from))
        except ValueError:
            year_from = ''
    if year_to:
        try:
            qs = qs.filter(release_year__lte=int(year_to))
        except ValueError:
            year_to = ''
    if min_rating:
        try:
            qs = qs.filter(tmdb_rating__gte=float(min_rating))
        except ValueError:
            min_rating = ''

    qs = qs.order_by(*_SORT_MAP[sort])

    paginator   = Paginator(qs, ITEMS_PER_PAGE)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    params_without_page = request.GET.copy()
    params_without_page.pop('page', None)
    base_query = params_without_page.urlencode()

    context = {
        'page_obj':    page_obj,
        'total_count': paginator.count,
        'base_query':  base_query,
        'platforms':   Platform.objects.order_by('name'),
        'genres':      Genre.objects.order_by('name'),
        'current_q':            q,
        'current_platform':     platform_slug,
        'current_genre':        genre_slug,
        'current_content_type': content_type,
        'current_year_from':    year_from,
        'current_year_to':      year_to,
        'current_min_rating':   min_rating,
        'current_sort':         sort,
        'min_rating_options': [
            ('6',   '6.0+'),
            ('7',   '7.0+'),
            ('7.5', '7.5+'),
            ('8',   '8.0+'),
            ('8.5', '8.5+'),
            ('9',   '9.0+'),
        ],
        'sort_options': [
            ('-rating', 'Rating: High to Low'),
            ('rating',  'Rating: Low to High'),
            ('-year',   'Year: Newest First'),
            ('year',    'Year: Oldest First'),
            ('title',   'Title: A to Z'),
            ('-title',  'Title: Z to A'),
        ],
    }
    return render(request, 'dashboard/explore.html', context)


# ── Content detail ────────────────────────────────────────────────────────────

def content_detail(request, pk):
    content = get_object_or_404(
        Content.objects.prefetch_related('genres', 'platforms', 'platform_links__platform'),
        pk=pk,
    )
    return render(request, 'dashboard/content_detail.html', {'content': content})


# ── Insights ──────────────────────────────────────────────────────────────────

def insights(request):
    total = Content.objects.count()

    if total == 0:
        return render(request, 'dashboard/insights.html', {'empty': True})

    genres         = analytics.genre_distribution()
    recent_genres  = analytics.genre_distribution(year_from=2015)
    platform_sizes = analytics.catalog_size_by_platform()
    ratings        = analytics.average_ratings_by_platform()
    year_data      = analytics.content_by_release_year()
    top_content    = list(analytics.highest_rated_content(min_votes=5, limit=5))

    movies_count = Content.objects.filter(content_type=Content.MOVIE).count()
    tv_count     = Content.objects.filter(content_type=Content.TV).count()

    # Decade distribution
    decade_counts: dict = {}
    for row in year_data:
        decade = (row['year'] // 10) * 10
        decade_counts[decade] = decade_counts.get(decade, 0) + row['count']
    sorted_decades   = sorted(decade_counts.items())
    top_decade_item  = max(decade_counts.items(), key=lambda x: x[1]) if decade_counts else None

    # Only show platform ratings backed by at least 3 rated titles
    reliable_ratings = [r for r in ratings if r['rated_count'] >= 3]

    context = {
        'empty':              False,
        'total':              total,
        'top_genres':         genres[:6],
        'top_genre':          genres[0] if genres else None,
        'top_recent_genres':  recent_genres[:3],
        'top_platform':       platform_sizes[0] if platform_sizes else None,
        'reliable_ratings':   reliable_ratings,
        'top_rated_platform': reliable_ratings[0] if reliable_ratings else None,
        'movies_count':       movies_count,
        'tv_count':           tv_count,
        'movies_pct':         round(movies_count / total * 100) if total else 0,
        'tv_pct':             round(tv_count / total * 100) if total else 0,
        'top_decade':         f"{top_decade_item[0]}s" if top_decade_item else None,
        'top_decade_count':   top_decade_item[1] if top_decade_item else None,
        'top_content':        top_content,
        'type_chart': {
            'labels': ['Movies', 'TV Shows'],
            'data':   [movies_count, tv_count],
        },
        'decade_chart': {
            'labels': [f"{d}s" for d, _ in sorted_decades],
            'data':   [c for _, c in sorted_decades],
        },
    }
    return render(request, 'dashboard/insights.html', context)
