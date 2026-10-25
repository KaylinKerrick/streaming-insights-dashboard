"""
Minimal TMDB API client using only the standard library (urllib).

Usage
-----
    from django.conf import settings
    from dashboard.services.tmdb_client import TMDBClient, TMDBError

    client = TMDBClient(settings.TMDB_API_KEY)

    # Single search
    results = client.search_multi("Spirited Away")
    fields  = client.movie_to_content_fields(client.get_movie(129))

    # Bulk fetch
    genre_map = {**client.get_genre_map("movie"), **client.get_genre_map("tv")}
    page      = client.fetch_list("movie", "popular", page=1)
    for result in page["results"]:
        fields = client.list_result_to_content_fields(result, "movie", genre_map)

API key / auth
--------------
TMDB supports two auth schemes:
  - Legacy api_key query param  (v3)
  - Bearer token Authorization header (v4 / recommended for new integrations)

This client uses the v3 api_key param because it is simpler for a CLI tool
and the Bearer token provides no extra benefit for read-only public requests.
Set TMDB_API_KEY in .env; the management command reads it from Django settings.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE_URL = "https://api.themoviedb.org/3"
_POSTER_BASE = "https://image.tmdb.org/t/p/w342"


class TMDBError(Exception):
    """Raised when the TMDB API returns an error or is unreachable."""


class TMDBClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise TMDBError(
                "TMDB_API_KEY is not set. Add it to your .env file and re-run."
            )
        self._api_key = api_key

    def _get(self, path: str, params: dict | None = None) -> Any:
        """Make a GET request and return the parsed JSON body."""
        query = {"api_key": self._api_key}
        if params:
            query.update(params)
        url = f"{_BASE_URL}{path}?{urllib.parse.urlencode(query)}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise TMDBError(f"HTTP {exc.code} from TMDB: {body}") from exc
        except urllib.error.URLError as exc:
            raise TMDBError(f"Network error reaching TMDB: {exc.reason}") from exc

    # ── Genre map ─────────────────────────────────────────────────────────────

    def get_genre_map(self, media_type: str) -> dict[int, str]:
        """
        Return {genre_id: genre_name} for 'movie' or 'tv'.
        Fetch once and pass into list_result_to_content_fields() for bulk imports.
        """
        data = self._get(f"/genre/{media_type}/list")
        return {g["id"]: g["name"] for g in data.get("genres", [])}

    # ── Bulk list fetch ───────────────────────────────────────────────────────

    def fetch_list(self, media_type: str, list_name: str, page: int = 1) -> dict:
        """
        Fetch one page from a TMDB paginated list.

        media_type : 'movie' or 'tv'
        list_name  : 'popular' or 'top_rated'

        Returns the raw TMDB response dict which includes:
            results      list of result dicts
            total_pages  int — total pages available
            total_results int
        """
        return self._get(f"/{media_type}/{list_name}", {"page": page})

    def list_result_to_content_fields(
        self,
        result: dict,
        media_type: str,
        genre_map: dict[int, str],
    ) -> dict:
        """
        Map a single item from a TMDB list response to Content model field values.

        List results carry genre_ids (ints) rather than full genre objects, so
        genre_map ({id: name}) must be obtained from get_genre_map() first.

        Returns a dict in the same shape as movie_to_content_fields().
        """
        if media_type == "movie":
            title    = result.get("title", "").strip()
            date_str = result.get("release_date", "")
        else:
            title    = result.get("name", "").strip()
            date_str = result.get("first_air_date", "")

        genre_ids   = result.get("genre_ids", [])
        genre_names = [genre_map[gid] for gid in genre_ids if gid in genre_map]

        return {
            "title":           title,
            "content_type":    "movie" if media_type == "movie" else "tv",
            "release_year":    self._parse_year(date_str),
            "overview":        (result.get("overview") or "").strip() or None,
            "tmdb_id":         result.get("id"),
            "tmdb_rating":     self._safe_decimal(result.get("vote_average")),
            "tmdb_vote_count": result.get("vote_count"),
            "poster_path":     result.get("poster_path") or "",
            "genre_names":     genre_names,
        }

    # ── Watch providers ───────────────────────────────────────────────────────

    def get_watch_providers(
        self,
        media_type: str,
        tmdb_id: int,
        region: str = "US",
    ) -> list[str]:
        """
        Return flatrate (subscription) streaming provider names for a title.

        Only "flatrate" entries are returned — rent/buy are excluded because
        we only want to record permanent catalog availability.

        Returns an empty list if no providers are found for the region.
        """
        data = self._get(f"/{media_type}/{tmdb_id}/watch/providers")
        region_data = data.get("results", {}).get(region, {})
        return [
            p["provider_name"]
            for p in region_data.get("flatrate", [])
            if "provider_name" in p
        ]

    # ── Search ────────────────────────────────────────────────────────────────

    def search_multi(self, query: str, page: int = 1) -> list[dict]:
        """
        Search movies and TV shows simultaneously.
        Returns a list of result dicts from the TMDB multi-search endpoint.
        Each result includes a 'media_type' key ('movie' or 'tv').
        """
        data = self._get("/search/multi", {"query": query, "page": page})
        return [r for r in data.get("results", []) if r.get("media_type") in ("movie", "tv")]

    # ── Detail fetches ────────────────────────────────────────────────────────

    def get_movie(self, tmdb_id: int) -> dict:
        """Fetch full movie detail from TMDB."""
        return self._get(f"/movie/{tmdb_id}", {"append_to_response": "genres"})

    def get_tv(self, tmdb_id: int) -> dict:
        """Fetch full TV show detail from TMDB."""
        return self._get(f"/tv/{tmdb_id}", {"append_to_response": "genres"})

    # ── Field mappers (detail responses) ─────────────────────────────────────

    def movie_to_content_fields(self, data: dict) -> dict:
        """
        Map a TMDB movie detail response to Content model field values.

        Returns a dict suitable for Content(**fields) or Content.objects.update().
        release_year is extracted from release_date ("YYYY-MM-DD").
        genre_names is a list of str — the caller must resolve Genre objects.
        """
        return {
            "title":           data.get("title", "").strip(),
            "content_type":    "movie",
            "release_year":    self._parse_year(data.get("release_date", "")),
            "overview":        (data.get("overview") or "").strip() or None,
            "tmdb_id":         data.get("id"),
            "tmdb_rating":     self._safe_decimal(data.get("vote_average")),
            "tmdb_vote_count": data.get("vote_count"),
            "poster_path":     data.get("poster_path") or "",
            "genre_names":     [g["name"] for g in data.get("genres", [])],
        }

    def tv_to_content_fields(self, data: dict) -> dict:
        """
        Map a TMDB TV detail response to Content model field values.
        first_air_date is used for release_year.
        """
        return {
            "title":           data.get("name", "").strip(),
            "content_type":    "tv",
            "release_year":    self._parse_year(data.get("first_air_date", "")),
            "overview":        (data.get("overview") or "").strip() or None,
            "tmdb_id":         data.get("id"),
            "tmdb_rating":     self._safe_decimal(data.get("vote_average")),
            "tmdb_vote_count": data.get("vote_count"),
            "poster_path":     data.get("poster_path") or "",
            "genre_names":     [g["name"] for g in data.get("genres", [])],
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_year(date_str: str) -> int | None:
        if date_str and len(date_str) >= 4:
            try:
                return int(date_str[:4])
            except ValueError:
                pass
        return None

    @staticmethod
    def _safe_decimal(value) -> float | None:
        """Return float if value is a valid TMDB rating (0.1–10), else None.
        TMDB returns 0.0 for unrated titles, so 0 is treated as absent."""
        try:
            f = float(value)
            return f if 0 < f <= 10 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def poster_url(poster_path: str) -> str:
        """Return full poster URL for a poster_path string."""
        if poster_path:
            return f"{_POSTER_BASE}{poster_path}"
        return ""
