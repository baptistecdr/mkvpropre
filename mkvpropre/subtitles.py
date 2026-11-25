"""Subtitle content analysis: event counts and SDH markers.

One analyser per codec (strategy). Text subtitles are always extracted (SDH
needs the text); image subtitles only when the file has no NUMBER_OF_FRAMES
statistics tag to count events from.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .model import ContentStats, MediaFile, Track
from .tools import run_tool

SDH_MARKERS = [
    re.compile(r"\[[^\]\n]{2,40}\]"),                                     # [MUSIC], [door slams]
    re.compile(r"^\s*-?\s*\([^)\n]{2,40}\)|\([^)\n]{2,40}\)\s*$", re.M),  # (laughs) at line start/end
    re.compile(r"[♪♫]|^#|#$", re.M),                                      # music
    re.compile(r"^\s*-?\s*[A-ZÀ-Ý][A-ZÀ-Ý0-9 .'’-]{1,24}:", re.M),        # MICHAEL: / - JAY:
]
MARKUP_RE = re.compile(r"<[^>]+>|\{[^}]*\}")                              # <i>, {\an8}


def parse_text_events(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r", "")
    events = []
    if path.suffix in (".ass", ".ssa"):
        for line in text.splitlines():
            if line.startswith("Dialogue:"):
                ev = line.split(",", 9)[-1].replace(r"\N", "\n").replace(r"\n", "\n")
                events.append(MARKUP_RE.sub("", ev).strip())
    else:  # srt / vtt: blocks separated by blank lines, text after the "-->" line
        for block in re.split(r"\n\s*\n", text):
            lines = block.strip().splitlines()
            timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
            if timing is None:
                continue
            ev = MARKUP_RE.sub("", "\n".join(lines[timing + 1:])).strip()
            if ev:
                events.append(ev)
    return events


def analyze_text(path: Path) -> ContentStats:
    events = parse_text_events(path)
    hits = sum(1 for ev in events if any(m.search(ev) for m in SDH_MARKERS))
    return ContentStats(len(events), hits / len(events) if events else 0.0)


def analyze_pgs(path: Path) -> ContentStats:
    """Count display sets (END segments); each subtitle is a show + a clear set."""
    data, pos, ends = path.read_bytes(), 0, 0
    while pos + 13 <= len(data) and data[pos:pos + 2] == b"PG":
        seg_type, size = data[pos + 10], int.from_bytes(data[pos + 11:pos + 13], "big")
        ends += seg_type == 0x80
        pos += 13 + size
    return ContentStats(ends // FRAMES_PER_EVENT["S_HDMV/PGS"])


def analyze_vobsub(path: Path) -> ContentStats:
    text = path.read_text(encoding="latin-1")
    return ContentStats(sum(1 for line in text.splitlines() if line.startswith("timestamp:")))


@dataclass(frozen=True)
class Analyzer:
    extension: str
    analyze: Callable[[Path], ContentStats]
    always: bool   # False: only when there is no frame-count tag


ANALYZERS: dict[str, Analyzer] = {
    "S_TEXT/UTF8": Analyzer("srt", analyze_text, True),
    "S_TEXT/ASS": Analyzer("ass", analyze_text, True),
    "S_TEXT/SSA": Analyzer("ssa", analyze_text, True),
    "S_TEXT/WEBVTT": Analyzer("vtt", analyze_text, True),
    "S_HDMV/PGS": Analyzer("sup", analyze_pgs, False),
    "S_VOBSUB": Analyzer("idx", analyze_vobsub, False),
}
FRAMES_PER_EVENT = {"S_HDMV/PGS": 2}  # PGS stores a "clear" display set per event


def analyze_subtitles(media: MediaFile) -> dict[int, ContentStats]:
    stats: dict[int, ContentStats] = {}
    jobs: list[tuple[Track, Analyzer]] = []
    for t in media.tracks:
        if t.type != "subtitles":
            continue
        frames = t.props.get("tag_number_of_frames")
        if frames is not None:
            stats[t.id] = ContentStats(int(frames) // FRAMES_PER_EVENT.get(t.codec, 1))
        analyzer = ANALYZERS.get(t.codec)
        if analyzer and (analyzer.always or t.id not in stats):
            jobs.append((t, analyzer))
    if jobs:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = [(t, a, Path(tmp) / f"track{t.id}.{a.extension}") for t, a in jobs]
            run_tool(["mkvextract", str(media.path), "tracks", "-q"]
                     + [f"{t.id}:{out}" for t, _, out in outputs])
            for t, a, out in outputs:
                stats[t.id] = a.analyze(out)
    return stats
