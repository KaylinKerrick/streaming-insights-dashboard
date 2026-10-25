from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify


class Genre(models.Model):
    """A content category such as Action, Comedy, or Documentary."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Platform(models.Model):
    """A streaming service such as Netflix or Disney+."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    website = models.URLField(max_length=200, blank=True, null=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Content(models.Model):
    """
    A single movie or TV show record.

    Ratings come from TMDB (scale 0–10). A null rating means the rating is
    unknown — it is never treated as zero. release_year is stored for datasets
    that do not provide a full date; add a release_date field when a source
    supplies one.
    """

    MOVIE = 'movie'
    TV = 'tv'
    CONTENT_TYPE_CHOICES = [
        (MOVIE, 'Movie'),
        (TV, 'TV Show'),
    ]

    title = models.CharField(max_length=500, db_index=True)
    content_type = models.CharField(
        max_length=10,
        choices=CONTENT_TYPE_CHOICES,
        db_index=True,
    )
    release_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        db_index=True,
    )
    overview = models.TextField(blank=True, null=True)

    genres = models.ManyToManyField(
        Genre,
        blank=True,
        related_name='content',
    )
    platforms = models.ManyToManyField(
        Platform,
        through='ContentPlatform',
        blank=True,
        related_name='content',
    )

    # External TMDB identifier — unique when present; multiple nulls are allowed
    # by both SQLite and PostgreSQL because NULL != NULL in SQL.
    tmdb_id = models.IntegerField(
        null=True,
        blank=True,
        unique=True,
        help_text='Numeric TMDB identifier. Unique when set.',
    )

    # DecimalField chosen over FloatField to avoid binary floating-point rounding.
    # TMDB publishes ratings on a 0–10 scale.
    tmdb_rating = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text='TMDB user rating (0.00–10.00). Null when unknown.',
    )
    tmdb_vote_count = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text='Number of TMDB user votes. Null when unknown.',
    )
    poster_path = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text='TMDB poster path (e.g. /abc123.jpg) or external URL.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']
        indexes = [
            models.Index(fields=['tmdb_rating']),
        ]
        verbose_name = 'Content'
        verbose_name_plural = 'Content'

    def __str__(self):
        year = f' ({self.release_year})' if self.release_year else ''
        return f'{self.title}{year}'

    @property
    def display_rating(self):
        """Return a formatted rating string, or None if unrated."""
        return f'{self.tmdb_rating:.1f}' if self.tmdb_rating is not None else None


class ContentPlatform(models.Model):
    """
    Explicit join table linking a Content record to a Platform.

    The region field defaults to an empty string (not NULL) so the
    UniqueConstraint works reliably across SQLite and PostgreSQL.
    A blank region means no specific region was recorded.

    IMPORTANT: records here represent associations found in the imported
    dataset — not verified, real-time streaming availability. The source
    field records where the association came from.
    """

    content = models.ForeignKey(
        Content,
        on_delete=models.CASCADE,
        related_name='platform_links',
    )
    platform = models.ForeignKey(
        Platform,
        on_delete=models.CASCADE,
        related_name='content_links',
    )
    # Empty string default lets UniqueConstraint work without NULL edge cases.
    region = models.CharField(max_length=10, blank=True, default='')
    availability_status = models.CharField(max_length=50, blank=True, null=True)
    last_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When this availability record was last confirmed.',
    )
    source = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text='Dataset or API that supplied this association.',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['content', 'platform', 'region'],
                name='unique_content_platform_region',
            )
        ]
        verbose_name = 'Content–Platform link'
        verbose_name_plural = 'Content–Platform links'

    def __str__(self):
        region_str = f' [{self.region}]' if self.region else ''
        return f'{self.content.title} on {self.platform.name}{region_str}'
