from django.contrib import admin

from .models import Content, ContentPlatform, Genre, Platform


class ContentPlatformInline(admin.TabularInline):
    model = ContentPlatform
    extra = 0
    fields = ['platform', 'region', 'availability_status', 'source', 'last_verified_at']


@admin.register(Content)
class ContentAdmin(admin.ModelAdmin):
    list_display = ['title', 'content_type', 'release_year', 'tmdb_rating', 'tmdb_vote_count']
    list_filter = ['content_type', 'genres', 'platforms']
    search_fields = ['title', 'overview']
    filter_horizontal = ['genres']
    inlines = [ContentPlatformInline]
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['title']
    list_per_page = 50


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'website']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(ContentPlatform)
class ContentPlatformAdmin(admin.ModelAdmin):
    list_display = ['content', 'platform', 'region', 'availability_status', 'source', 'last_verified_at']
    list_filter = ['platform']
    search_fields = ['content__title', 'platform__name']
