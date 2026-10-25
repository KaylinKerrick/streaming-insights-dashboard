"""
Management command: fetch_tmdb

Three modes:

  Bulk mode  (fetch titles)
  -------------------------
      python manage.py fetch_tmdb --bulk
      python manage.py fetch_tmdb --bulk --pages 20
      python manage.py fetch_tmdb --bulk --pages 10 --content-type movie

  Link-platforms mode  (attach streaming providers to existing titles)
  ---------------------------------------------------------------------
  Reads every Content record that has a tmdb_id, calls the TMDB watch-providers
  endpoint for each, and creates ContentPlatform rows for any matching platform.
  Run this after --bulk to populate the platform charts.

      python manage.py fetch_tmdb --link-platforms
      python manage.py fetch_tmdb --link-platforms --region GB
      python manage.py fetch_tmdb --link-platforms --skip-linked

  Single / search mode  (one title at a time)
  --------------------------------------------
      python manage.py fetch_tmdb --query "Spirited Away"
      python manage.py fetch_tmdb --query "The Bear" --save-first
      python manage.py fetch_tmdb --movie-id 129 --save-first
      python manage.py fetch_tmdb --tv-id 85552 --save-first

Requires TMDB_API_KEY in .env.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from dashboard.models import Content, ContentPlatform, Genre, Platform
from dashboard.services.tmdb_client import TMDBClient, TMDBError

_LISTS = {
    "movie": ["popular", "top_rated"],
    "tv":    ["popular", "top_rated"],
}

# Maps TMDB provider names to the names used in the seeded Platform records.
_PROVIDER_MAP = {
    "Netflix":            "Netflix",
    "Amazon Prime Video": "Prime Video",
    "Prime Video":        "Prime Video",
    "Disney Plus":        "Disney+",
    "Disney+":            "Disney+",
    "Hulu":               "Hulu",
    "Max":                "Max",
    "HBO Max":            "Max",
    "Apple TV Plus":      "Apple TV+",
    "Apple TV+":          "Apple TV+",
}


class Command(BaseCommand):
    help = "Fetch metadata from the TMDB API and optionally save to the database."

    def add_arguments(self, parser):
        # Bulk mode
        parser.add_argument("--bulk", action="store_true", default=False,
                            help="Fetch TMDB popular/top-rated lists and save all results.")
        parser.add_argument("--pages", type=int, default=5, metavar="N",
                            help="Pages per list in bulk mode (default: 5, 20 titles/page).")
        parser.add_argument("--content-type", choices=["movie", "tv"], dest="content_type",
                            default=None, help="Limit bulk fetch to 'movie' or 'tv'.")

        # Link-platforms mode
        parser.add_argument("--link-platforms", action="store_true", default=False,
                            dest="link_platforms",
                            help="Fetch watch providers for all Content records and create platform links.")
        parser.add_argument("--region", type=str, default="US", metavar="CODE",
                            help="Two-letter region code for watch providers (default: US).")
        parser.add_argument("--skip-linked", action="store_true", default=False,
                            dest="skip_linked",
                            help="Skip titles that already have at least one platform link.")

        # Single / search mode
        parser.add_argument("--query",    type=str, metavar="TITLE",
                            help="Title to search for.")
        parser.add_argument("--movie-id", type=int, metavar="ID", dest="movie_id",
                            help="Fetch a specific TMDB movie by ID.")
        parser.add_argument("--tv-id",    type=int, metavar="ID", dest="tv_id",
                            help="Fetch a specific TMDB TV show by ID.")
        parser.add_argument("--save-first", action="store_true", default=False,
                            help="Save the first result to the database.")

    def handle(self, *args, **options):
        api_key = getattr(settings, "TMDB_API_KEY", "")
        try:
            client = TMDBClient(api_key)
        except TMDBError as exc:
            raise CommandError(str(exc)) from exc

        if options["bulk"]:
            self._run_bulk(client, options)
        elif options["link_platforms"]:
            self._run_link_platforms(client, options)
        else:
            self._run_single(client, options)

    # ── Link-platforms mode ───────────────────────────────────────────────────

    def _run_link_platforms(self, client: TMDBClient, options: dict) -> None:
        region      = options["region"].upper()
        skip_linked = options["skip_linked"]

        # Pre-load known platforms into a name → Platform dict for fast lookup.
        known_platforms = {p.name: p for p in Platform.objects.all()}

        qs = Content.objects.filter(tmdb_id__isnull=False).order_by("id")
        if skip_linked:
            qs = qs.filter(platform_links__isnull=True).distinct()

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No eligible titles found."))
            return

        self.stdout.write(
            f"Linking platforms for {total} title(s) — region: {region}."
            "\nThis makes one API call per title; ~"
            f"{total // 4} seconds at 0.25 s/call.\n"
        )

        links_created = links_skipped = errors = 0

        for i, content in enumerate(qs.iterator(), start=1):
            media_type = "movie" if content.content_type == Content.MOVIE else "tv"
            try:
                provider_names = client.get_watch_providers(
                    media_type, content.tmdb_id, region
                )
            except TMDBError as exc:
                self.stdout.write(
                    self.style.WARNING(f"  [{i}/{total}] {content.title}: {exc}")
                )
                errors += 1
                time.sleep(0.25)
                continue

            for raw_name in provider_names:
                our_name = _PROVIDER_MAP.get(raw_name)
                if not our_name:
                    continue
                platform = known_platforms.get(our_name)
                if not platform:
                    continue
                _, created = ContentPlatform.objects.get_or_create(
                    content=content,
                    platform=platform,
                    region=region,
                    defaults={
                        "availability_status": "available",
                        "last_verified_at":    timezone.now(),
                        "source":              "tmdb_watch_providers",
                    },
                )
                if created:
                    links_created += 1
                else:
                    links_skipped += 1

            if i % 50 == 0 or i == total:
                self.stdout.write(f"  {i}/{total} processed — {links_created} links created so far")

            time.sleep(0.25)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Links created: {links_created}  "
                f"Already existed: {links_skipped}  "
                f"Errors: {errors}"
            )
        )

    # ── Bulk mode ─────────────────────────────────────────────────────────────

    def _run_bulk(self, client: TMDBClient, options: dict) -> None:
        pages        = options["pages"]
        content_type = options["content_type"]
        media_types  = [content_type] if content_type else ["movie", "tv"]

        total_created = total_updated = 0

        self.stdout.write("Fetching genre maps...")
        try:
            genre_map: dict[int, str] = {}
            for mt in media_types:
                genre_map.update(client.get_genre_map(mt))
        except TMDBError as exc:
            raise CommandError(f"Could not fetch genre map: {exc}") from exc

        for media_type in media_types:
            for list_name in _LISTS[media_type]:
                self.stdout.write(
                    f"\nFetching {media_type}/{list_name} — {pages} page(s)..."
                )
                for page_num in range(1, pages + 1):
                    try:
                        page_data = client.fetch_list(media_type, list_name, page=page_num)
                    except TMDBError as exc:
                        self.stdout.write(
                            self.style.WARNING(f"  Page {page_num} failed: {exc} — skipping.")
                        )
                        break

                    results     = page_data.get("results", [])
                    total_pages = page_data.get("total_pages", 1)
                    created = updated = skipped = 0

                    for result in results:
                        fields = client.list_result_to_content_fields(
                            result, media_type, genre_map
                        )
                        if not fields.get("tmdb_id") or not fields.get("title"):
                            skipped += 1
                            continue
                        was_created = self._save_content(fields, silent=True)
                        if was_created:
                            created += 1
                        else:
                            updated += 1

                    total_created += created
                    total_updated += updated
                    capped = min(page_num, total_pages)
                    self.stdout.write(
                        f"  Page {capped}/{min(pages, total_pages)}: "
                        f"+{created} new, {updated} updated"
                        + (f", {skipped} skipped" if skipped else "")
                    )

                    if page_num >= total_pages:
                        break

                    time.sleep(0.25)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created: {total_created}  Updated: {total_updated}"
                "\nRun --link-platforms next to attach streaming providers."
            )
        )

    # ── Single / search mode ──────────────────────────────────────────────────

    def _run_single(self, client: TMDBClient, options: dict) -> None:
        query    = options.get("query")
        movie_id = options.get("movie_id")
        tv_id    = options.get("tv_id")
        save     = options["save_first"]

        if not any([query, movie_id, tv_id]):
            raise CommandError(
                "Provide --query, --movie-id, --tv-id, --bulk, or --link-platforms. "
                "Run with --help for examples."
            )

        fields_list = []

        try:
            if query:
                self.stdout.write(f"Searching TMDB for: {query!r} ...")
                results = client.search_multi(query)
                if not results:
                    self.stdout.write(self.style.WARNING("No results found."))
                    return
                self._print_search_results(results)
                if save:
                    top = results[0]
                    mt  = top.get("media_type")
                    tid = top.get("id")
                    self.stdout.write(
                        f"\nFetching full detail (id={tid}, type={mt}) ..."
                    )
                    if mt == "movie":
                        fields_list.append(client.movie_to_content_fields(client.get_movie(tid)))
                    else:
                        fields_list.append(client.tv_to_content_fields(client.get_tv(tid)))

            elif movie_id:
                self.stdout.write(f"Fetching TMDB movie id={movie_id} ...")
                fields_list.append(client.movie_to_content_fields(client.get_movie(movie_id)))

            elif tv_id:
                self.stdout.write(f"Fetching TMDB TV id={tv_id} ...")
                fields_list.append(client.tv_to_content_fields(client.get_tv(tv_id)))

        except TMDBError as exc:
            raise CommandError(f"TMDB API error: {exc}") from exc

        for fields in fields_list:
            self._display_fields(fields)
            if save:
                created = self._save_content(fields, silent=False)
                verb = "Created" if created else "Updated"
                obj  = Content.objects.get(tmdb_id=fields["tmdb_id"])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n{verb}: {obj.title!r} (pk={obj.pk}, tmdb_id={obj.tmdb_id})"
                    )
                )

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _save_content(self, fields: dict, *, silent: bool) -> bool:
        """Upsert a Content record. Returns True if created, False if updated."""
        genre_names: list[str] = fields.pop("genre_names", [])
        tmdb_id = fields.get("tmdb_id")

        if not tmdb_id:
            if not silent:
                self.stdout.write(self.style.ERROR("No tmdb_id — cannot save."))
            return False

        with transaction.atomic():
            obj, created = Content.objects.update_or_create(
                tmdb_id=tmdb_id,
                defaults={k: v for k, v in fields.items() if v is not None},
            )
            genres = []
            for name in genre_names:
                slug  = name.lower().replace(" ", "-").replace("&", "and")
                genre, _ = Genre.objects.get_or_create(
                    slug=slug, defaults={"name": name}
                )
                genres.append(genre)
            obj.genres.set(genres)

        return created

    def _print_search_results(self, results: list[dict]) -> None:
        self.stdout.write(f"\nFound {len(results)} result(s):\n")
        for i, r in enumerate(results[:10], start=1):
            media   = r.get("media_type", "?")
            title   = r.get("title") or r.get("name", "Unknown")
            year    = (r.get("release_date") or r.get("first_air_date") or "")[:4]
            rating  = r.get("vote_average")
            tmdb_id = r.get("id")
            rating_str = f"  rating={rating:.1f}" if rating else ""
            self.stdout.write(
                f"  [{i}] {title} ({year}) [{media}] id={tmdb_id}{rating_str}"
            )

    def _display_fields(self, fields: dict) -> None:
        self.stdout.write("\n--- Fetched fields ---")
        for key, val in fields.items():
            if key == "genre_names":
                self.stdout.write(f"  genres:           {', '.join(val) or '(none)'}")
            else:
                self.stdout.write(f"  {key:<20}{val!r}")
