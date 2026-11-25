"""Title and original language (VO) of each file, looked up with FileBot.

Episodes (file name contains SxxEyy): the show's episode list is fetched once
per show, `filebot -list --db TheMovieDB::TV`, and matched on SxxEyy.
Movies (no SxxEyy): one `filebot -list --db TheMovieDB` query per movie, built
from the name and year in the file name.

`-list` is used (not `-rename`) because it needs no FileBot licence and never
touches the files.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

EpisodeKey = tuple[int, int]            # (season, episode)

EPISODE_RE = re.compile(r"S(\d{1,2})E(\d{1,3})", re.I)
SEASON_DIR_RE = re.compile(r"(season|saison|series|s)[ ._-]*\d+|specials|extras", re.I)
YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
RELEASE_TAG_RE = re.compile(
    r"(?:^|[ ._\-\[(])(2160p|1080p|720p|576p|480p|4k|uhd|multi|truefrench|french|vostfr|vff|vfq|vfi|"
    r"bluray|blu-ray|bdrip|brrip|web|web-?dl|webrip|hdtv|dvdrip|remux|x26[45]|h\.?26[45]|hevc|avc|"
    r"proper|repack|extended|unrated|remastered)(?![a-z0-9])", re.I)


class FileBotError(Exception):
    """FileBot couldn't answer (no match, licence, network, ...)."""


@dataclass(frozen=True)
class FileInfo:
    title: str | None = None
    original: str | None = None      # ISO 639-1, e.g. "en", "fr", "ja"
    source: str = ""                 # what it was matched as, for the logs


@dataclass(frozen=True)
class SeriesInfo:
    titles: dict[EpisodeKey, str]
    original: str | None


@dataclass(frozen=True)
class MovieInfo:
    title: str
    year: int | None
    original: str | None
    original_title: str = ""


# --- Names from paths ------------------------------------------------------------------

def episode_key(path: Path) -> EpisodeKey | None:
    m = EPISODE_RE.search(path.name)
    return (int(m[1]), int(m[2])) if m else None


def _clean(name: str) -> str:
    name = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", name)   # leading [Group] tags
    name = re.sub(r"[._]+", " ", name)
    return re.sub(r"\s+", " ", name).strip(" -[]")


def show_name(path: Path) -> str | None:
    """'My Wife And Kids.S01E01.MULTI…mkv' -> 'My Wife And Kids'.

    When the filename starts with SxxEyy, the closest folder that isn't a
    season folder is used instead ('My Wife And Kids/Season 1/S01E01.mkv').
    """
    m = EPISODE_RE.search(path.stem)
    if m and _clean(path.stem[:m.start()]):
        return _clean(path.stem[:m.start()])
    for parent in path.parents:
        if parent.name and not SEASON_DIR_RE.fullmatch(parent.name.strip()):
            return _clean(parent.name) or None
    return None


def movie_query(path: Path) -> tuple[str, int | None] | None:
    """'Amelie.2001.MULTI.1080p.BluRay.x264-GROUP.mkv' -> ('Amelie', 2001).

    The year is the last plausible one before the release tags, so a year in the
    title itself stays in the name: 'Blade.Runner.2049.2017…' -> ('Blade Runner 2049', 2017),
    '2001.A.Space.Odyssey.1968…' -> ('2001 A Space Odyssey', 1968).
    """
    stem = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", path.stem)
    tag = RELEASE_TAG_RE.search(stem)
    head = stem[:tag.start()] if tag else stem
    latest = date.today().year + 1
    years = [m for m in YEAR_RE.finditer(head)
             if int(m[1]) <= latest and _clean(head[:m.start()]).rstrip(" ([")]
    year = years[-1] if years else None
    name = _clean(head[:year.start()] if year else head).rstrip(" ([")
    return (name, int(year[1]) if year else None) if name else None


# --- FileBot -------------------------------------------------------------------------------

def filebot_available() -> bool:
    return shutil.which("filebot") is not None


def _primary(lang: str) -> str | None:
    lang = lang.strip().lower().replace("_", "-")
    return lang.split("-")[0] or None


def filebot_list(query: str, db: str, lang: str, fields: list[str]) -> list[list[str]]:
    """Rows of `filebot -list`, one tab-separated field per binding."""
    cmd = ["filebot", "-list", "--q", query, "--db", db, "--lang", lang, "--format", "\t".join(fields)]
    log.info("   $ %s", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    rows = [line.split("\t") for line in res.stdout.splitlines()]
    rows = [r for r in rows if len(r) == len(fields)]   # FileBot logs go to stderr, but be strict
    if res.returncode != 0 or not rows:
        output = "\n".join(s.strip() for s in (res.stdout, res.stderr) if s.strip())
        tail = "\n".join(output.splitlines()[-3:]) or "no results"
        raise FileBotError(f"FileBot found nothing for {query!r} in {db} (exit {res.returncode}): {tail}")
    return rows


def fetch_series(show: str, db: str, lang: str) -> SeriesInfo:
    rows = filebot_list(show, db, lang, ["{s00e00}", "{t}", "{info.originalLanguage}"])
    titles: dict[EpisodeKey, str] = {}
    original = None
    for key, title, orig in rows:
        m = EPISODE_RE.fullmatch(key.strip())
        if m and title.strip():
            titles[(int(m[1]), int(m[2]))] = " ".join(title.split())
            original = original or _primary(orig)
    if not titles:
        raise FileBotError(f"FileBot returned no episodes for {show!r}")
    return SeriesInfo(titles, original)


def fetch_movie(query: str, lang: str) -> MovieInfo:
    rows = filebot_list(query, "TheMovieDB", lang, ["{n}", "{y}", "{info.originalLanguage}", "{primaryTitle}"])
    title, year, orig, original_title = rows[0]       # FileBot returns its best match first
    return MovieInfo(" ".join(title.split()), int(year) if year.isdigit() else None,
                     _primary(orig), original_title.strip())


# --- Resolver --------------------------------------------------------------------------------

SeriesFetcher = Callable[[str, str, str], SeriesInfo]
MovieFetcher = Callable[[str, str], MovieInfo]


@dataclass
class Lookup:
    """Call prepare() once with all files (one FileBot query per show / movie), then info_for()."""
    db: str = "TheMovieDB::TV"       # for series; movies always use TheMovieDB
    lang: str = "fr"
    show: str | None = None          # --show: skip show-name detection
    movie: str | None = None         # --movie: skip movie-name detection
    series_fetcher: SeriesFetcher = fetch_series
    movie_fetcher: MovieFetcher = fetch_movie
    _series: dict[str, SeriesInfo | None] = field(default_factory=dict, init=False)
    _movies: dict[str, MovieInfo | None] = field(default_factory=dict, init=False)

    def prepare(self, files: list[Path]) -> None:
        by_show: dict[str | None, list[Path]] = {}
        for f in files:
            if episode_key(f):
                by_show.setdefault(self._show_of(f), []).append(f)
            else:
                self._movie_for(f)
        if None in by_show:
            log.warning("   ! can't tell the show name of %s, use --show",
                        ", ".join(f.name for f in by_show.pop(None)))
        for show, show_files in sorted(by_show.items()):
            series = self._series_for(show)
            if series:
                not_found = sorted({k for f in show_files if (k := episode_key(f)) not in series.titles})
                if not_found:
                    log.warning("   ! %r: not in FileBot's list: %s", show,
                                ", ".join(f"S{s:02}E{e:02}" for s, e in not_found))

    def info_for(self, path: Path) -> FileInfo:
        key = episode_key(path)
        if key:
            show = self._show_of(path)
            series = self._series.get(show) if show else None
            if not series:
                return FileInfo()
            return FileInfo(series.titles.get(key), series.original,
                            f"{show} S{key[0]:02}E{key[1]:02}")
        movie = self._movies.get(self._movie_query(path) or "")
        if not movie:
            return FileInfo()
        return FileInfo(movie.title, movie.original, f"movie {movie.original_title or movie.title} ({movie.year})")

    # --- internals

    def _show_of(self, path: Path) -> str | None:
        return self.show or show_name(path)

    def _movie_query(self, path: Path) -> str | None:
        if self.movie:
            return self.movie
        q = movie_query(path)
        return f"{q[0]} {q[1]}" if q and q[1] else (q[0] if q else None)

    def _series_for(self, show: str) -> SeriesInfo | None:
        if show not in self._series:
            log.info("\n== looking up series %r (FileBot, %s, %s)", show, self.db, self.lang)
            try:
                info = self.series_fetcher(show, self.db, self.lang)
                log.info("   %d episodes, VO: %s", len(info.titles), info.original or "?")
            except (FileBotError, OSError) as e:
                log.error("   ✗ %s", e)
                info = None
            self._series[show] = info
        return self._series[show]

    def _movie_for(self, path: Path) -> MovieInfo | None:
        query = self._movie_query(path)
        if not query:
            log.warning("   ! can't tell the movie name of %s, use --movie", path.name)
            return None
        if query not in self._movies:
            log.info("\n== looking up movie %r (FileBot, TheMovieDB, %s)", query, self.lang)
            try:
                info = self.movie_fetcher(query, self.lang)
                log.info("   -> %s (%s), VO: %s", info.title, info.year or "?", info.original or "?")
                wanted = movie_query(path)
                if not self.movie and wanted and wanted[1] and info.year and abs(info.year - wanted[1]) > 1:
                    log.warning("   ! file says %d but FileBot matched %d: check it, or use --movie",
                                wanted[1], info.year)
                if not self.movie and not (wanted and wanted[1]):
                    log.warning("   ! no year in the file name, the match may be wrong: check it, or use --movie")
            except (FileBotError, OSError) as e:
                log.error("   ✗ %s", e)
                info = None
            self._movies[query] = info
        return self._movies[query]
