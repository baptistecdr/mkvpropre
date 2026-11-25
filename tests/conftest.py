"""Builders for in-memory MediaFile objects, shaped like `mkvmerge -J` output."""
from __future__ import annotations

from pathlib import Path

import pytest

from mkvpropre.config import Config
from mkvpropre.model import ContentStats, MediaFile, Track

MINUTES_21 = 21 * 60 * 10**9


def track(id: int, type: str, *, lang: str | None = None, ietf: str | None = None,
          name: str | None = None, codec: str | None = None, number: int | None = None,
          **props) -> Track:
    """props: raw mkvmerge keys, e.g. default_track=True, forced_track=True."""
    codec = codec or {"video": "V_MPEGH/ISO/HEVC", "audio": "A_EAC3", "subtitles": "S_TEXT/UTF8"}[type]
    p = {"number": number if number is not None else id + 1, "codec_id": codec}
    if lang is not None:
        p["language"] = lang
    if ietf is not None:
        p["language_ietf"] = ietf
    if name is not None:
        p["track_name"] = name
    p.update(props)
    return Track(id, p["number"], type, codec, p)


def media(*tracks: Track, title: str = "", attachments=(), has_tags: bool = False,
          content: dict | None = None, duration_ns: int | None = MINUTES_21) -> MediaFile:
    return MediaFile(Path("Show.S01E01.mkv"), title, duration_ns, tuple(tracks),
                     tuple(attachments), has_tags, content or {})


def stats(events: int | None = None, sdh_ratio: float | None = None) -> ContentStats:
    return ContentStats(events, sdh_ratio)


@pytest.fixture
def cfg() -> Config:
    return Config()


@pytest.fixture
def user_file() -> MediaFile:
    """The episode from the original question: VF default, release-group names."""
    return media(
        track(0, "video", lang="eng", ietf="en", name="1080p WEB D+", default_track=True),
        track(1, "audio", lang="eng", ietf="en", name="EN EAC3 5.1", default_track=False),
        track(2, "audio", lang="fre", ietf="fr", name="FR EAC3 2.0", default_track=True),
        track(3, "subtitles", lang="eng", ietf="en", name="EN", default_track=False),
        track(4, "subtitles", lang="fre", ietf="fr", name="FR", default_track=False),
        title="My Wife And Kids.S01E01.MULTI.1080p.WEB.H265-FTMVHD",
        content={3: stats(394, 0.0), 4: stats(366, 0.0)},
    )
