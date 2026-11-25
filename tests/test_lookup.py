"""Title and VO lookup with FileBot, for episodes and movies."""
from __future__ import annotations

import logging
import stat
from pathlib import Path

import pytest

import normalize_mkv.cli
from normalize_mkv.config import Config
from normalize_mkv.lookup import (FileBotError, FileInfo, Lookup, MovieInfo, SeriesInfo, episode_key,
                                  fetch_movie, fetch_series, movie_query, show_name)

RELEASE = "My Wife And Kids.S01E{:02}.MULTI.1080p.WEB.H265-FTMVHD.mkv"


# --- names ---------------------------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("My Wife And Kids.S01E01.MULTI.1080p.WEB.H265-FTMVHD.mkv", (1, 1)),
    ("my.wife.and.kids.s02e113.mkv", (2, 113)),
    ("My Wife And Kids - Pilot.mkv", None),
])
def test_episode_key(name, expected):
    assert episode_key(Path(name)) == expected


@pytest.mark.parametrize("path, expected", [
    ("x/My Wife And Kids.S01E01.MULTI.1080p.WEB.H265-FTMVHD.mkv", "My Wife And Kids"),
    ("x/my.wife.and.kids.s01e01.mkv", "my wife and kids"),
    ("x/My_Wife_And_Kids_-_S01E01.mkv", "My Wife And Kids"),
    ("x/[Group] My Wife And Kids (2001) - S01E01.mkv", "My Wife And Kids (2001)"),
    ("x/[A][B] My.Wife.And.Kids.S01E01.mkv", "My Wife And Kids"),
    ("My Wife And Kids (2001)/Season 1/S01E01.mkv", "My Wife And Kids (2001)"),
    ("My Wife And Kids/Saison 02/S02E01 - Titre.mkv", "My Wife And Kids"),
    ("My.Wife.And.Kids/S01/S01E01.mkv", "My Wife And Kids"),
])
def test_show_name(path, expected):
    assert show_name(Path("/media") / path) == expected


@pytest.mark.parametrize("name, expected", [
    ("Amelie.2001.MULTI.1080p.BluRay.x264-GROUP.mkv", ("Amelie", 2001)),
    ("Mission.Impossible.Fallout.2018.1080p.WEB.mkv", ("Mission Impossible Fallout", 2018)),
    ("Dune (2021) [1080p].mkv", ("Dune", 2021)),
    ("Dune.Part.Two.2024.MULTI.2160p.mkv", ("Dune Part Two", 2024)),
    ("2001.A.Space.Odyssey.1968.1080p.mkv", ("2001 A Space Odyssey", 1968)),   # title starts with a year
    ("Blade.Runner.2049.2017.MULTi.mkv", ("Blade Runner 2049", 2017)),
    ("Blade.Runner.2049.mkv", ("Blade Runner 2049", None)),                     # future year = title
    ("Mission.Impossible.Fallout.2018.REPACK.1080p.mkv", ("Mission Impossible Fallout", 2018)),
    ("[Group] Le Prénom.FRENCH.1080p.WEB.mkv", ("Le Prénom", None)),              # no year: cut at tags
    ("Le Prénom.mkv", ("Le Prénom", None)),
    ("1080p.mkv", None),
])
def test_movie_query(name, expected):
    assert movie_query(Path(name)) == expected


# --- FileBot -------------------------------------------------------------------------------

@pytest.fixture
def fake_filebot(tmp_path, monkeypatch):
    """Put a fake `filebot` on PATH; returns a function to set its output and exit code."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "filebot"
    args_file = tmp_path / "filebot-args"

    def setup(stdout: str, exit_code: int = 0, stderr: str = "Fetching data\n"):
        (tmp_path / "stdout").write_text(stdout, encoding="utf-8")
        (tmp_path / "stderr").write_text(stderr, encoding="utf-8")
        script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{args_file}"\n'
                          f'cat "{tmp_path / "stdout"}"\ncat "{tmp_path / "stderr"}" >&2\nexit {exit_code}\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return lambda: args_file.read_text(encoding="utf-8").splitlines()

    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return setup


def test_fetch_series(fake_filebot):
    args = fake_filebot("S01E01\tUn papa en or\ten\nS01E02\tLa  vérité blesse\ten\nnoise\nS00E01\tSpécial\ten\n")
    info = fetch_series("My Wife and Kids", "TheMovieDB::TV", "fr")
    assert info == SeriesInfo({(1, 1): "Un papa en or", (1, 2): "La vérité blesse", (0, 1): "Spécial"}, "en")
    assert args() == ["-list", "--q", "My Wife and Kids", "--db", "TheMovieDB::TV", "--lang", "fr",
                      "--format", "{s00e00}\t{t}\t{info.originalLanguage}"]


def test_fetch_movie(fake_filebot):
    args = fake_filebot("Le Fabuleux Destin d'Amélie Poulain\t2001\tfr\tLe Fabuleux Destin d'Amélie Poulain\n")
    assert fetch_movie("Amelie 2001", "fr") == MovieInfo("Le Fabuleux Destin d'Amélie Poulain", 2001, "fr",
                                                         "Le Fabuleux Destin d'Amélie Poulain")
    assert args()[:6] == ["-list", "--q", "Amelie 2001", "--db", "TheMovieDB", "--lang"]


def test_fetch_movie_takes_first_match_and_normalizes_language(fake_filebot):
    fake_filebot("Le Voyage de Chihiro\t2001\tja_JP\tSpirited Away\nAutre\t2002\ten\tOther\n")
    assert fetch_movie("Spirited Away", "fr") == MovieInfo("Le Voyage de Chihiro", 2001, "ja", "Spirited Away")


def test_fetch_no_result(fake_filebot):
    fake_filebot("", exit_code=3, stderr="No search results\nFailure\n")
    with pytest.raises(FileBotError, match="No search results"):
        fetch_movie("zzqxw", "fr")


def test_fetch_series_licence_error(fake_filebot):
    fake_filebot("", exit_code=1, stderr="Bad License\n")
    with pytest.raises(FileBotError, match="Bad License"):
        fetch_series("My Wife and Kids", "TheMovieDB::TV", "fr")


# --- Lookup ------------------------------------------------------------------------------------

class Fakes:
    def __init__(self, series=None, movies=None, fail=False):
        self.series = series or {"My Wife And Kids": SeriesInfo(
            {(1, 1): "Un papa en or", (1, 2): "La vérité blesse", (2, 1): "Saison deux"}, "en")}
        self.movies = movies or {"Amelie 2001": MovieInfo("Le Fabuleux Destin d'Amélie Poulain", 2001, "fr",
                                                          "Le Fabuleux Destin d'Amélie Poulain")}
        self.fail = fail
        self.calls: list[tuple] = []

    def series_fetcher(self, show, db, lang):
        self.calls.append(("series", show, db, lang))
        if self.fail or show not in self.series:
            raise FileBotError(f"FileBot found nothing for {show!r}")
        return self.series[show]

    def movie_fetcher(self, query, lang):
        self.calls.append(("movie", query, lang))
        if self.fail or query not in self.movies:
            raise FileBotError(f"FileBot found nothing for {query!r}")
        return self.movies[query]

    def lookup(self, **kw) -> Lookup:
        return Lookup(series_fetcher=self.series_fetcher, movie_fetcher=self.movie_fetcher, **kw)


def episodes(folder: Path, *numbers: int, pattern: str = RELEASE) -> list[Path]:
    return [folder / pattern.format(n) for n in numbers]


def test_episode_info(tmp_path):
    fakes = Fakes()
    files = episodes(tmp_path, 1, 2)
    lk = fakes.lookup(db="TVmaze", lang="en")
    lk.prepare(files)
    assert lk.info_for(files[0]) == FileInfo("Un papa en or", "en", "My Wife And Kids S01E01")
    assert lk.info_for(files[1]).title == "La vérité blesse"
    assert fakes.calls == [("series", "My Wife And Kids", "TVmaze", "en")]


def test_series_fetched_once_across_season_folders(tmp_path):
    fakes = Fakes()
    files = episodes(tmp_path / "Season 1", 1, 2) + \
        episodes(tmp_path / "Season 2", 1, pattern=RELEASE.replace("S01", "S02"))
    lk = fakes.lookup()
    lk.prepare(files)
    assert len(fakes.calls) == 1
    assert lk.info_for(files[2]).title == "Saison deux"


def test_movie_info(tmp_path):
    fakes = Fakes()
    f = tmp_path / "Amelie.2001.MULTI.1080p.BluRay.x264-GROUP.mkv"
    lk = fakes.lookup()
    lk.prepare([f])
    assert lk.info_for(f) == FileInfo("Le Fabuleux Destin d'Amélie Poulain", "fr",
                                      "movie Le Fabuleux Destin d'Amélie Poulain (2001)")
    assert fakes.calls == [("movie", "Amelie 2001", "fr")]


def test_episodes_and_movies_in_one_run(tmp_path):
    fakes = Fakes()
    ep = episodes(tmp_path / "Series", 1)
    movie = tmp_path / "Movies" / "Amelie.2001.mkv"
    lk = fakes.lookup()
    lk.prepare(ep + [movie])
    assert lk.info_for(ep[0]).original == "en" and lk.info_for(movie).original == "fr"
    assert sorted(c[0] for c in fakes.calls) == ["movie", "series"]


def test_movie_option_overrides_detection(tmp_path):
    fakes = Fakes(movies={"Amélie (2001)": MovieInfo("Amélie", 2001, "fr")})
    f = tmp_path / "amelie-final-v2.mkv"
    lk = fakes.lookup(movie="Amélie (2001)")
    lk.prepare([f])
    assert fakes.calls == [("movie", "Amélie (2001)", "fr")]
    assert lk.info_for(f).title == "Amélie"


def test_show_option_overrides_detection(tmp_path):
    fakes = Fakes(series={"My Wife and Kids (2001)": SeriesInfo({(1, 1): "Un papa en or"}, "en")})
    files = episodes(tmp_path, 1, pattern="S01E{:02}.mkv")
    lk = fakes.lookup(show="My Wife and Kids (2001)")
    lk.prepare(files)
    assert lk.info_for(files[0]).title == "Un papa en or"


def test_movie_year_mismatch_warns(tmp_path, caplog):
    fakes = Fakes(movies={"Dune 1984": MovieInfo("Dune", 2021, "en")})
    f = tmp_path / "Dune.1984.mkv"
    with caplog.at_level(logging.WARNING):
        fakes.lookup().prepare([f])
    assert "file says 1984 but FileBot matched 2021" in caplog.text


def test_movie_without_year_warns(tmp_path, caplog):
    fakes = Fakes(movies={"Le Prénom": MovieInfo("Le Prénom", 2012, "fr")})
    with caplog.at_level(logging.WARNING):
        fakes.lookup().prepare([tmp_path / "Le Prénom.FRENCH.1080p.mkv"])
    assert "no year in the file name" in caplog.text


def test_episodes_filebot_does_not_know_are_reported(tmp_path, caplog):
    files = episodes(tmp_path, 1, 9)
    lk = Fakes().lookup()
    with caplog.at_level(logging.WARNING):
        lk.prepare(files)
    assert lk.info_for(files[1]) == FileInfo(None, "en", "My Wife And Kids S01E09")
    assert "not in FileBot's list: S01E09" in caplog.text


def test_failures_are_logged_not_fatal(tmp_path, caplog):
    fakes = Fakes(fail=True)
    files = episodes(tmp_path, 1) + [tmp_path / "Amelie.2001.mkv"]
    lk = fakes.lookup()
    with caplog.at_level(logging.ERROR):
        lk.prepare(files)
    assert lk.info_for(files[0]) == FileInfo() and lk.info_for(files[1]) == FileInfo()
    assert caplog.text.count("FileBot found nothing") == 2


# --- CLI ---------------------------------------------------------------------------------------

def test_cli_requires_filebot_unless_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(normalize_mkv.cli, "missing_tools", lambda: [])
    monkeypatch.setattr(normalize_mkv.cli, "filebot_available", lambda: False)
    assert normalize_mkv.cli.main([str(tmp_path)]) == 2
    assert normalize_mkv.cli.main(["--no-filebot", str(tmp_path)]) == 0     # empty folder


@pytest.mark.parametrize("info, original, expected_vo, expected_audio", [
    (FileInfo("Amélie", "fr", "movie"), None, "fr", "fr"),     # FileBot's VO
    (FileInfo("Dune", "en", "movie"), None, "en", "en"),
    (FileInfo("Amélie", "fr", "movie"), "en", "en", "en"),     # --original wins
    (FileInfo("Chihiro", "ja", "movie"), None, "ja", "en"),    # unsupported VO: default audio falls back
    (FileInfo(), None, "en", "en"),                            # nothing known: defaults
])
def test_file_config(info, original, expected_vo, expected_audio):
    cfg, _ = normalize_mkv.cli.file_config(Config(), info, original)
    assert (cfg.original, cfg.default_audio) == (expected_vo, expected_audio)
