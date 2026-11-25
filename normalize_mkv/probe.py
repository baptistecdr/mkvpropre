"""Read a Matroska file into a MediaFile."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .config import Config
from .model import Attachment, MediaFile, Track
from .subtitles import analyze_subtitles
from .tools import ToolError, run_tool


def read_media(path: Path) -> MediaFile:
    """Metadata only (`mkvmerge -J`), no subtitle analysis."""
    info = json.loads(run_tool(["mkvmerge", "-J", str(path)]))
    if not info.get("container", {}).get("recognized"):
        raise ToolError("not a file mkvmerge can read")
    cp = info["container"].get("properties", {})
    return MediaFile(
        path=path,
        title=cp.get("title") or "",
        duration_ns=cp.get("duration"),
        tracks=tuple(Track.from_json(t) for t in info.get("tracks", [])),
        attachments=tuple(Attachment(a["id"], a.get("file_name", "?"), a.get("content_type") or "")
                          for a in info.get("attachments", [])),
        has_tags=bool(info.get("global_tags") or info.get("track_tags")),
    )


def probe(path: Path, cfg: Config) -> MediaFile:
    """Metadata plus subtitle content analysis (unless disabled)."""
    media = read_media(path)
    if cfg.use_content:
        media = replace(media, content=analyze_subtitles(media))
    return media
