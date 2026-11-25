"""Hardening against hostile download names, links and races (security review)."""
from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

import mkvpropre.files
import mkvpropre.library
from mkvpropre.cli import find_files
from mkvpropre.files import exclusive_temp, rename_no_overwrite
from mkvpropre.library import LibraryError, library_path, move_to_library
from mkvpropre.lookup import Naming


# --- file scan ---------------------------------------------------------------------------------

def test_symlinks_found_in_a_folder_are_skipped(tmp_path, caplog):
    precious = tmp_path / "elsewhere" / "My Movie (2001).mkv"
    precious.parent.mkdir()
    precious.write_bytes(b"precious")
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "Real.S01E01.mkv").write_bytes(b"")
    (downloads / "Evil.S01E02.mkv").symlink_to(precious)
    assert [p.name for p in find_files([downloads])] == ["Real.S01E01.mkv"]
    assert "skipping symlink" in caplog.text


def test_paths_are_absolute_so_names_never_look_like_options(tmp_path, monkeypatch):
    (tmp_path / "-o.mkv").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    [found] = find_files([Path(".")])
    assert found.is_absolute() and not str(found).startswith("-")
    assert find_files([Path("-o.mkv")]) == [tmp_path / "-o.mkv"]


# --- temp files -----------------------------------------------------------------------------------

def test_exclusive_temp_is_new_hidden_and_unpredictable(tmp_path):
    a, b = exclusive_temp(tmp_path / "x.mkv", ".tmp.mkv"), exclusive_temp(tmp_path / "x.mkv", ".tmp.mkv")
    assert a != b and a.exists() and a.stat().st_size == 0
    assert a.name.startswith(".x.") and a.name.endswith(".tmp.mkv")


def test_exclusive_temp_never_reuses_a_planted_file(tmp_path, monkeypatch):
    target = tmp_path / "victim"
    target.write_bytes(b"victim")
    names = iter(["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
    monkeypatch.setattr(mkvpropre.files.secrets, "token_hex", lambda n: next(names))
    (tmp_path / ".x.aaaaaaaaaaaa.tmp").symlink_to(target)        # attacker guessed the first name
    tmp = exclusive_temp(tmp_path / "x.mkv", ".tmp")
    assert tmp.name == ".x.bbbbbbbbbbbb.tmp" and not tmp.is_symlink()
    assert target.read_bytes() == b"victim"


# --- moves never overwrite ---------------------------------------------------------------------

def test_rename_no_overwrite_refuses_existing_destination(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.write_bytes(b"new")
    dest.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        rename_no_overwrite(src, dest)
    assert dest.read_bytes() == b"old" and src.read_bytes() == b"new"


def test_rename_no_overwrite_refuses_a_dangling_symlink(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.write_bytes(b"new")
    dest.symlink_to(tmp_path / "nowhere")
    with pytest.raises(FileExistsError):
        rename_no_overwrite(src, dest)
    assert not (tmp_path / "nowhere").exists()


def test_rename_no_overwrite_without_hard_links(tmp_path, monkeypatch):
    def no_links(*args, **kwargs):
        raise OSError(errno.EPERM, "Operation not permitted")
    monkeypatch.setattr(mkvpropre.files.os, "link", no_links)
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.write_bytes(b"data")
    rename_no_overwrite(src, dest)
    assert dest.read_bytes() == b"data" and not src.exists()
    src.write_bytes(b"other")
    with pytest.raises(FileExistsError):
        rename_no_overwrite(src, dest)
    assert dest.read_bytes() == b"data"


def test_destination_appearing_after_the_check_is_not_overwritten(tmp_path, monkeypatch):
    src = tmp_path / "downloads" / "Amelie.2001.mkv"
    src.parent.mkdir()
    src.write_bytes(b"download")
    dest = tmp_path / "cinemas" / "movies" / "Amélie (2001).mkv"

    def race(a, b):                       # another process creates dest right after our exists() check
        dest.write_bytes(b"theirs")
        return True

    monkeypatch.setattr(mkvpropre.library, "same_file_system", race)
    with pytest.raises(LibraryError, match="already exists"):
        move_to_library(src, dest, dry=False)
    assert dest.read_bytes() == b"theirs" and src.read_bytes() == b"download"


def test_cross_device_copy_uses_an_unpredictable_part_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mkvpropre.library, "same_file_system", lambda a, b: False)
    src = tmp_path / "downloads" / "Amelie.2001.mkv"
    src.parent.mkdir()
    src.write_bytes(b"download")
    dest = tmp_path / "cinemas" / "movies" / "Amélie (2001).mkv"
    dest.parent.mkdir(parents=True)
    (dest.parent / f".{dest.name}.part").symlink_to(tmp_path / "victim")    # old, predictable name
    move_to_library(src, dest, dry=False)
    assert dest.read_bytes() == b"download" and not (tmp_path / "victim").exists()


# --- degenerate names from TheMovieDB ------------------------------------------------------------

@pytest.mark.parametrize("naming", [
    Naming("movie", "..", 2001),
    Naming("movie", "  ...  ", None),
    Naming("movie", "???", 1999),
    Naming("episode", "..", 2001, season=1, episode=1, episode_title="Pilot"),
    Naming("episode", "", None, season=1, episode=1),
])
def test_unusable_names_are_refused(naming):
    with pytest.raises(LibraryError, match="unusable"):
        library_path(Path("/lib"), naming)


def test_empty_saga_or_episode_title_is_just_dropped():
    assert library_path(Path("/lib"), Naming("movie", "Film", 2001, collection="??")) == \
        Path("/lib/movies/Film (2001).mkv")
    assert library_path(Path("/lib"), Naming("episode", "Show", 2001, season=1, episode=2, episode_title="...")) == \
        Path("/lib/tvshows/Show (2001)/Season 01/Show (2001) - S01E02.mkv")


@pytest.mark.parametrize("name", ["../../etc/passwd", "/abs/olute", "a/../../b", "C:\\Windows"])
def test_names_never_escape_the_library(name):
    root = Path("/lib")
    for naming in (Naming("movie", name, 2001, collection=name),
                   Naming("episode", name, 2001, season=1, episode=1, episode_title=name)):
        p = library_path(root, naming)
        assert p.is_relative_to(root) and ".." not in p.parts and len(p.parts) <= 6
