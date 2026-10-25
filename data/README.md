# Data Directory

## sample_content.csv

**Purpose:** Development and testing. 25 hand-curated records covering both movies
and TV shows, all six seeded platforms, and a variety of genres.

**Source:** Hand-assembled from publicly available TMDB metadata.
TMDB IDs and ratings reflect real records but overviews have been shortened.

**Access date:** 2026-10-25

**License / attribution:** TMDB data is used under the
[TMDB API Terms of Use](https://www.themoviedb.org/documentation/api/terms-of-use).
Attribution: "This product uses the TMDB API but is not endorsed or certified by TMDB."

**Known limitations:**
- 25 records — for testing only.
- Platform associations are illustrative; they do not reflect current availability.
- Overviews have been shortened from official TMDB text.
- `poster_path` column is intentionally empty in this sample.

---

## CSV column reference

| Column           | Required | Description |
|------------------|----------|-------------|
| `title`          | Yes      | Title of the movie or TV show |
| `content_type`   | Yes      | `movie` or `tv` |
| `release_year`   | No       | 4-digit year (or `YYYY-MM-DD` — year is extracted) |
| `genres`         | No       | Pipe-separated genre names e.g. `Action\|Drama` |
| `overview`       | No       | Short description |
| `tmdb_id`        | No       | Numeric TMDB identifier (used as the unique key when present) |
| `tmdb_rating`    | No       | TMDB rating 0–10 (decimal) |
| `tmdb_vote_count`| No       | Number of TMDB votes (integer ≥ 0) |
| `poster_path`    | No       | TMDB poster path e.g. `/abc123.jpg` |
| `platforms`      | No       | Pipe-separated platform names matching seeded names exactly |

### Deduplication

- If `tmdb_id` is present it is the unique key. The same ID will update the
  existing record rather than create a duplicate.
- If `tmdb_id` is absent the importer falls back to `(title, content_type,
  release_year)` as a natural key. This cannot guarantee uniqueness for titles
  that genuinely share a name and year.

---

## Getting a larger dataset

For a production-quality dataset consider:

### Option A — Kaggle: "Movies on Netflix, Prime Video, Hulu and Disney+"
- Search for this dataset on kaggle.com
- Contains ~9,000 titles with platform availability flags (Netflix/Hulu/Disney+/Prime)
- Columns need to be mapped to the import format (see `import_content` command)
- Verify the license before use (typically CC0 or similar)

### Option B — TMDB export via API
- Register at https://developer.themoviedb.org/
- Use `python manage.py fetch_tmdb --query "..."` (Milestone 8)
- Full dataset exports are available to approved API users

### Option C — TMDB community datasets
- TMDB publishes periodic data exports at https://developer.themoviedb.org/docs/daily-id-exports
- Requires processing to convert to the import CSV format

---

## What NOT to commit

- Large CSV files (>5 MB) — add them to `.gitignore`
- Files with redistribution restrictions
- Files containing personal or sensitive data
