-- =============================================================================
-- Streaming Insights Dashboard -- SQL Analytics Examples
-- =============================================================================
-- These queries run against the Django-generated schema.
-- Table names follow Django's convention: <app>_<modelname>
--
-- Key tables:
--   dashboard_content          -- movies and TV shows
--   dashboard_genre            -- genre records
--   dashboard_platform         -- streaming platform records
--   dashboard_contentplatform  -- explicit many-to-many join (content <-> platform)
--   dashboard_content_genres   -- auto many-to-many join (content <-> genre)
--
-- All examples can be run in the Django shell with:
--   from django.db import connection
--   cursor = connection.cursor()
--   cursor.execute("<query>", [param1, param2])
--   rows = cursor.fetchall()
--
-- Or directly against the SQLite database:
--   sqlite3 db.sqlite3 ".read sql/analytics_examples.sql"
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. SELECT -- basic retrieval
-- -----------------------------------------------------------------------------

-- All movies ordered alphabetically
SELECT title, release_year, tmdb_rating
FROM   dashboard_content
WHERE  content_type = 'movie'
ORDER  BY title ASC;

-- All TV shows ordered by release year (newest first)
SELECT title, release_year, tmdb_rating
FROM   dashboard_content
WHERE  content_type = 'tv'
ORDER  BY release_year DESC;


-- -----------------------------------------------------------------------------
-- 2. FILTER -- by release year and rating
-- -----------------------------------------------------------------------------

-- Titles released after 2015 with a rating above 8
SELECT title, content_type, release_year, tmdb_rating
FROM   dashboard_content
WHERE  release_year > 2015
  AND  tmdb_rating  > 8.0
ORDER  BY tmdb_rating DESC;

-- Titles with no rating recorded (NULL -- never stored as 0)
SELECT title, content_type, release_year
FROM   dashboard_content
WHERE  tmdb_rating IS NULL
ORDER  BY title;


-- -----------------------------------------------------------------------------
-- 3. SORT AND LIMIT -- top results
-- -----------------------------------------------------------------------------

-- Top 10 highest-rated titles with at least 5000 votes
-- (min_votes avoids statistical outliers from titles with very few votes)
SELECT title, content_type, release_year, tmdb_rating, tmdb_vote_count
FROM   dashboard_content
WHERE  tmdb_rating    IS NOT NULL
  AND  tmdb_vote_count >= 5000
ORDER  BY tmdb_rating DESC, title ASC
LIMIT  10;

-- 5 most recent titles (by release year)
SELECT title, content_type, release_year
FROM   dashboard_content
WHERE  release_year IS NOT NULL
ORDER  BY release_year DESC, title ASC
LIMIT  5;


-- -----------------------------------------------------------------------------
-- 4. COUNT -- titles per platform
-- -----------------------------------------------------------------------------

-- Number of distinct content titles associated with each platform
-- Uses DISTINCT to avoid double-counting if the same title appears on multiple
-- regions of the same platform (i.e. multiple contentplatform rows).
SELECT   p.name            AS platform,
         COUNT(DISTINCT cp.content_id) AS title_count
FROM     dashboard_platform p
JOIN     dashboard_contentplatform cp ON cp.platform_id = p.id
GROUP BY p.id, p.name
ORDER BY title_count DESC;

-- Breakdown of movies vs TV shows per platform
SELECT   p.name       AS platform,
         c.content_type,
         COUNT(DISTINCT c.id) AS count
FROM     dashboard_platform p
JOIN     dashboard_contentplatform cp ON cp.platform_id = p.id
JOIN     dashboard_content c          ON c.id = cp.content_id
GROUP BY p.id, p.name, c.content_type
ORDER BY p.name, c.content_type;


-- -----------------------------------------------------------------------------
-- 5. JOIN -- content with genres
-- -----------------------------------------------------------------------------

-- All titles and their genres (one row per content-genre pair)
-- dashboard_content_genres is the auto-generated M2M join table.
SELECT c.title, c.release_year, g.name AS genre
FROM   dashboard_content c
JOIN   dashboard_content_genres cg ON cg.content_id = c.id
JOIN   dashboard_genre g           ON g.id = cg.genre_id
ORDER  BY c.title, g.name;

-- Titles that belong to the Drama genre
SELECT c.title, c.content_type, c.release_year, c.tmdb_rating
FROM   dashboard_content c
JOIN   dashboard_content_genres cg ON cg.content_id = c.id
JOIN   dashboard_genre g           ON g.id = cg.genre_id
WHERE  g.slug = 'drama'
ORDER  BY c.tmdb_rating DESC;


-- -----------------------------------------------------------------------------
-- 6. JOIN -- content with platforms
-- -----------------------------------------------------------------------------

-- All titles and which platforms they are associated with
SELECT c.title, c.content_type, p.name AS platform
FROM   dashboard_content c
JOIN   dashboard_contentplatform cp ON cp.content_id = c.id
JOIN   dashboard_platform p         ON p.id = cp.platform_id
ORDER  BY c.title, p.name;

-- Netflix titles only
SELECT c.title, c.content_type, c.release_year, c.tmdb_rating
FROM   dashboard_content c
JOIN   dashboard_contentplatform cp ON cp.content_id = c.id
JOIN   dashboard_platform p         ON p.id = cp.platform_id
WHERE  p.slug = 'netflix'
ORDER  BY c.tmdb_rating DESC;


-- -----------------------------------------------------------------------------
-- 7. GROUP BY genre -- title counts per genre
-- -----------------------------------------------------------------------------

-- Number of titles per genre, sorted by most common
-- Note: a title can appear in multiple genres, so genre counts overlap.
-- The sum of all counts will exceed the total number of unique titles.
SELECT   g.name          AS genre,
         COUNT(DISTINCT c.id) AS title_count
FROM     dashboard_genre g
JOIN     dashboard_content_genres cg ON cg.genre_id = g.id
JOIN     dashboard_content c         ON c.id = cg.content_id
GROUP BY g.id, g.name
ORDER BY title_count DESC;

-- Genre counts for movies only
SELECT   g.name               AS genre,
         COUNT(DISTINCT c.id) AS movie_count
FROM     dashboard_genre g
JOIN     dashboard_content_genres cg ON cg.genre_id  = g.id
JOIN     dashboard_content c         ON c.id          = cg.content_id
WHERE    c.content_type = 'movie'
GROUP BY g.id, g.name
ORDER BY movie_count DESC;


-- -----------------------------------------------------------------------------
-- 8. AGGREGATE -- average rating by platform
-- -----------------------------------------------------------------------------

-- Average TMDB rating per platform, excluding unrated titles.
-- ROUND(..., 2) keeps the display manageable.
-- rated_count lets the viewer assess whether the average is meaningful.
SELECT   p.name                        AS platform,
         ROUND(AVG(c.tmdb_rating), 2)  AS avg_rating,
         COUNT(DISTINCT c.id)          AS rated_count
FROM     dashboard_platform p
JOIN     dashboard_contentplatform cp ON cp.platform_id = p.id
JOIN     dashboard_content c          ON c.id = cp.content_id
WHERE    c.tmdb_rating IS NOT NULL
GROUP BY p.id, p.name
HAVING   COUNT(DISTINCT c.id) > 0
ORDER BY avg_rating DESC;

-- Same query but also show total titles (rated + unrated) for context
SELECT   p.name                                     AS platform,
         ROUND(AVG(c.tmdb_rating), 2)               AS avg_rating,
         COUNT(DISTINCT CASE WHEN c.tmdb_rating IS NOT NULL THEN c.id END) AS rated_count,
         COUNT(DISTINCT c.id)                       AS total_count
FROM     dashboard_platform p
JOIN     dashboard_contentplatform cp ON cp.platform_id = p.id
JOIN     dashboard_content c          ON c.id = cp.content_id
GROUP BY p.id, p.name
ORDER BY avg_rating DESC;


-- -----------------------------------------------------------------------------
-- 9. COMPARE TWO PLATFORMS
-- -----------------------------------------------------------------------------

-- Compare Netflix and Max side by side
-- Replace 'netflix' / 'max' with any two platform slugs.
SELECT
    p.name                              AS platform,
    COUNT(DISTINCT c.id)                AS total_titles,
    COUNT(DISTINCT CASE WHEN c.content_type = 'movie' THEN c.id END) AS movies,
    COUNT(DISTINCT CASE WHEN c.content_type = 'tv'    THEN c.id END) AS tv_shows,
    ROUND(AVG(c.tmdb_rating), 2)        AS avg_rating,
    COUNT(DISTINCT CASE WHEN c.tmdb_rating IS NOT NULL THEN c.id END) AS rated_titles
FROM   dashboard_platform p
JOIN   dashboard_contentplatform cp ON cp.platform_id = p.id
JOIN   dashboard_content c          ON c.id = cp.content_id
WHERE  p.slug IN ('netflix', 'max')
GROUP  BY p.id, p.name
ORDER  BY total_titles DESC;

-- Genres exclusive to Platform A but not Platform B (Netflix - Max)
SELECT DISTINCT g.name AS genre_on_netflix_not_max
FROM   dashboard_genre g
JOIN   dashboard_content_genres cg ON cg.genre_id  = g.id
JOIN   dashboard_content c         ON c.id          = cg.content_id
JOIN   dashboard_contentplatform cp ON cp.content_id = c.id
JOIN   dashboard_platform p         ON p.id          = cp.platform_id
WHERE  p.slug = 'netflix'
  AND  g.id NOT IN (
      SELECT g2.id
      FROM   dashboard_genre g2
      JOIN   dashboard_content_genres cg2 ON cg2.genre_id   = g2.id
      JOIN   dashboard_content c2         ON c2.id           = cg2.content_id
      JOIN   dashboard_contentplatform cp2 ON cp2.content_id = c2.id
      JOIN   dashboard_platform p2         ON p2.id          = cp2.platform_id
      WHERE  p2.slug = 'max'
  )
ORDER  BY genre_on_netflix_not_max;


-- -----------------------------------------------------------------------------
-- 10. FILTER by genre and year range
-- -----------------------------------------------------------------------------

-- Drama titles released between 2015 and 2022
SELECT c.title, c.content_type, c.release_year, c.tmdb_rating
FROM   dashboard_content c
JOIN   dashboard_content_genres cg ON cg.content_id = c.id
JOIN   dashboard_genre g           ON g.id = cg.genre_id
WHERE  g.slug = 'drama'
  AND  c.release_year BETWEEN 2015 AND 2022
ORDER  BY c.release_year DESC, c.tmdb_rating DESC;

-- Most common genres for titles released in the last decade
SELECT   g.name               AS genre,
         COUNT(DISTINCT c.id) AS count
FROM     dashboard_genre g
JOIN     dashboard_content_genres cg ON cg.genre_id = g.id
JOIN     dashboard_content c         ON c.id = cg.content_id
WHERE    c.release_year >= 2015
GROUP BY g.id, g.name
ORDER BY count DESC
LIMIT    5;
