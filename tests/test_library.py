"""Library paths and moves (--library)."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

import mkvpropre.cli
import mkvpropre.library
from mkvpropre.library import LibraryError, library_path, move_to_library, safe_name, saga_folder
from mkvpropre.lookup import Naming

ROOT = Path("/media/raid/cinemas")


# --- names -----------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Amélie", "Amélie"),
    ("Mission: Impossible - Fallout", "Mission - Impossible - Fallout"),
    ("Star Wars: Episode IV - A New Hope", "Star Wars - Episode IV - A New Hope"),
    ("AC/DC: Let There Be Rock", "AC-DC - Let There Be Rock"),
    ('What "If"?', "What If"),
    ("  Dots at the end...  ", "Dots at the end"),
    ("Call My Agent!", "Call My Agent!"),
])
def test_safe_name(text, expected):
    assert safe_name(text) == expected


@pytest.mark.parametrize("collection, expected", [
    ("Star Wars Collection", "Star Wars"),
    ("Mission: Impossible Collection", "Mission - Impossible"),
    ("The Lord of the Rings Collection", "The Lord of the Rings"),
    ("Collection", "Collection"),
])
def test_saga_folder(collection, expected):
    assert saga_folder(collection) == expected


# --- paths ----------------------------------------------------------------------------------

@pytest.mark.parametrize("naming, expected", [
    (Naming("movie", "Amélie", 2001), "movies/Amélie (2001).mkv"),
    (Naming("movie", "Mission: Impossible - Fallout", 2018, collection="Mission: Impossible Collection"),
     "movies/Mission - Impossible/Mission - Impossible - Fallout (2018).mkv"),
    (Naming("movie", "Star Wars", 1977, collection="Star Wars Collection"),
     "movies/Star Wars/Star Wars (1977).mkv"),
    (Naming("movie", "Untitled", None), "movies/Untitled.mkv"),
    (Naming("episode", "My Wife and Kids", 2001, season=1, episode=2, episode_title="The Truth Hurts"),
     "tvshows/My Wife and Kids (2001)/Season 01/My Wife and Kids (2001) - S01E02 - The Truth Hurts.mkv"),
    (Naming("episode", "My Wife and Kids", 2001, season=5, episode=12, episode_title=None),
     "tvshows/My Wife and Kids (2001)/Season 05/My Wife and Kids (2001) - S05E12.mkv"),
    (Naming("episode", "Call My Agent!", 2015, season=0, episode=1, episode_title="Making of: part 1"),
     "tvshows/Call My Agent! (2015)/Specials/Call My Agent! (2015) - S00E01 - Making of - part 1.mkv"),
])
def test_library_path(naming, expected):
    assert library_path(ROOT, naming) == ROOT / expected


# --- moves ----------------------------------------------------------------------------------

@pytest.fixture
def download(tmp_path) -> Path:
    f = tmp_path / "downloads" / "Amelie.2001" / "Amelie.2001.MULTI.1080p.mkv"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"movie data")
    return f


def test_move_creates_folders(tmp_path, download):
    dest = tmp_path / "cinemas" / "movies" / "Star Wars" / "Star Wars (1977).mkv"
    assert move_to_library(download, dest, dry=False) is True
    assert dest.read_bytes() == b"movie data" and not download.exists()


def test_move_across_file_systems_copies_then_deletes(tmp_path, download, monkeypatch):
    monkeypatch.setattr(mkvpropre.library, "same_file_system", lambda a, b: False)
    dest = tmp_path / "cinemas" / "movies" / "Amélie (2001).mkv"
    move_to_library(download, dest, dry=False)
    assert dest.read_bytes() == b"movie data" and not download.exists()
    assert [p.name for p in dest.parent.iterdir()] == ["Amélie (2001).mkv"]     # no .part left


def test_failed_copy_keeps_the_original(tmp_path, download, monkeypatch):
    monkeypatch.setattr(mkvpropre.library, "same_file_system", lambda a, b: False)

    def broken_copy(src, dst):
        Path(dst).write_bytes(b"half")
        raise OSError("No space left on device")

    monkeypatch.setattr(mkvpropre.library.shutil, "copy2", broken_copy)
    dest = tmp_path / "cinemas" / "movies" / "Amélie (2001).mkv"
    with pytest.raises(OSError, match="No space"):
        move_to_library(download, dest, dry=False)
    assert download.read_bytes() == b"movie data"
    assert list(dest.parent.iterdir()) == []                                     # .part cleaned up


def test_never_overwrites(tmp_path, download):
    dest = tmp_path / "cinemas" / "movies" / "Amélie (2001).mkv"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"already there")
    with pytest.raises(LibraryError, match="already exists"):
        move_to_library(download, dest, dry=False)
    assert dest.read_bytes() == b"already there" and download.exists()


def test_dry_run_moves_nothing(tmp_path, download, caplog):
    dest = tmp_path / "cinemas" / "movies" / "Amélie (2001).mkv"
    with caplog.at_level(logging.INFO):
        move_to_library(download, dest, dry=True)
    assert download.exists() and not dest.parent.exists()
    assert f"would move to {dest}" in caplog.text


def test_file_already_in_place(tmp_path, caplog):
    f = tmp_path / "movies" / "Amélie (2001).mkv"
    f.parent.mkdir()
    f.write_bytes(b"x")
    with caplog.at_level(logging.INFO):
        assert move_to_library(f, f, dry=False) is False
    assert f.exists() and "already in the library" in caplog.text


# --- CLI checks ----------------------------------------------------------------------------------

def test_cli_library_needs_filebot(tmp_path, monkeypatch):
    monkeypatch.setattr(mkvpropre.cli, "missing_tools", lambda: [])
    assert mkvpropre.cli.main(["--no-filebot", "--library", str(tmp_path), str(tmp_path)]) == 2


def test_cli_library_must_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(mkvpropre.cli, "missing_tools", lambda: [])
    monkeypatch.setattr(mkvpropre.cli, "filebot_available", lambda: True)
    assert mkvpropre.cli.main(["--library", str(tmp_path / "nope"), str(tmp_path)]) == 2
