# Streaming Insights Dashboard

This is a Django web app for exploring movie and TV show data across popular streaming platforms. With this dashboard you can browse the full catalog, filter by genre, platform, rating, and release year, and also view varioys analytics charts showing trends across the dataset.

Built as a personal portfolio project using Python, Django, SQLite, Chart.js, and Bootstrap 5. Also developed with Claude Code as an AI pair programming tool to speed up workflow and review code.


---

## How to Run

**1. Clone the repo and create a virtual environment**
```bash
git clone <repo-url>
cd streaming-services-dashboard
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Set up environment variables**
```bash
cp .env.example .env
```
Open `.env` and fill in a `DJANGO_SECRET_KEY`. Add a `TMDB_API_KEY` if you want to import live data (free at [developer.themoviedb.org](https://developer.themoviedb.org/)).

**4. Run migrations**
```bash
python manage.py migrate
```

**5. Import data**
```bash
# Import the included 25-title sample dataset
python manage.py import_content data/sample_content.csv

# Or fetch real data from TMDB (requires API key)
python manage.py fetch_tmdb --bulk --pages 10
python manage.py fetch_tmdb --link-platforms
```

**6. Start the server**
```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000/`

---

## Data

The original sample dataset I used (`data/sample_content.csv`) contained 25 titles covering six streaming platforms.

For a larger dataset, the app integrates with the **TMDB API** (The Movie Database). Running `fetch_tmdb --bulk` pulls from TMDB's popular and top-rated lists for movies and TV, and `fetch_tmdb --link-platforms` maps each title to its streaming platforms using TMDB's watch provider data.

All the data including titles, ratings, genres, overviews, and poster images come from TMDB.

> This product uses the TMDB API but is not endorsed or certified by TMDB.
