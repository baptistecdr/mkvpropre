"""Where a normalized file goes in the library, and moving it there safely.

Layout (English names, Plex / Jellyfin conventions):

  <library>/movies/Amélie (2001).mkv                              movie
  <library>/movies/Star Wars/Star Wars (1977).mkv                 movie of a saga
  <library>/tvshows/My Wife and Kids (2001)/Season 01/
        My Wife and Kids (2001) - S01E01 - Pilot.mkv               episode
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from .lookup import Naming

log = logging.getLogger(__name__)

MOVIES = "movies"
TVSHOWS = "tvshows"

INVALID_CHARS_RE = re.compile(r'[<>"\\|?*\x00-\x1f]')
COLLECTION_SUFFIX_RE = re.compile(r"\s*[-:]?\s*(collection|saga|trilogy|anthology)$", re.I)


class LibraryError(Exception):
    pass


def safe_name(text: str) -> str:
    """A file / folder name that works on Linux, macOS and SMB shares.

    'Mission: Impossible - Fallout' -> 'Mission - Impossible - Fallout'
    """
    text = re.sub(r"\s*:\s*", " - ", text)            # "Mission: Impossible", "Star Wars: Episode IV"
    text = text.replace("/", "-")                      # "AC/DC"
    text = INVALID_CHARS_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"( - )+", " - ", text)
    return text.strip(" .")                            # no leading/trailing dots or spaces (SMB)


def saga_folder(collection: str) -> str:
    """'Star Wars Collection' -> 'Star Wars'."""
    return safe_name(COLLECTION_SUFFIX_RE.sub("", collection)) or safe_name(collection)


def with_year(name: str, year: int | None) -> str:
    return f"{name} ({year})" if year else name


def library_path(root: Path, naming: Naming) -> Path:
    if naming.kind == "movie":
        folder = root / MOVIES
        if naming.collection:
            folder /= saga_folder(naming.collection)
        return folder / f"{safe_name(with_year(naming.name, naming.year))}.mkv"

    show = safe_name(with_year(naming.name, naming.year))
    season, episode = naming.season or 0, naming.episode or 0
    season_dir = "Specials" if season == 0 else f"Season {season:02}"
    filename = f"{show} - S{season:02}E{episode:02}"
    if naming.episode_title:
        filename += f" - {safe_name(naming.episode_title)}"
    return root / TVSHOWS / show / season_dir / f"{filename}.mkv"


def same_file_system(a: Path, b: Path) -> bool:
    return a.stat().st_dev == b.stat().st_dev


def move_to_library(src: Path, dest: Path, dry: bool) -> bool:
    """Move `src` to `dest`, never overwriting. Across file systems: copy, check, then delete.

    Returns True if the file was (or, in a dry run, would be) moved.
    """
    if src.resolve() == dest.resolve():
        log.info("   already in the library")
        return False
    if dest.exists():
        raise LibraryError(f"not moved, {dest} already exists")
    if dry:
        log.info("   would move to %s", dest)
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    if same_file_system(src, dest.parent):
        os.rename(src, dest)                           # same file system: instant
    else:
        part = dest.with_name(f".{dest.name}.part")
        try:
            shutil.copy2(src, part)
            if part.stat().st_size != src.stat().st_size:
                raise LibraryError(f"copy of {src.name} is incomplete, original kept")
            if dest.exists():
                raise LibraryError(f"not moved, {dest} appeared during the copy")
            os.replace(part, dest)
        finally:
            part.unlink(missing_ok=True)
        src.unlink()
    log.info("   moved to %s", dest)
    return True
