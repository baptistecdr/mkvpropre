"""Language detection and subtitle content analysis."""
from __future__ import annotations

import struct

import pytest

from mkvpropre.model import ContentStats
from mkvpropre.subtitles import ANALYZERS, SDH_MARKERS, analyze_pgs, analyze_text, analyze_vobsub, parse_text_events
from mkvpropre.plan import detect_lang
from conftest import track


# --- detect_lang -----------------------------------------------------------------

@pytest.mark.parametrize("lang, ietf, name, expected", [
    ("eng", "en", None, "en"),
    ("fre", "fr", None, "fr"),
    ("fra", None, None, "fr"),            # ISO 639-2/T spelling
    ("fre", "fr-CA", None, "fr"),         # regional tag -> primary subtag
    ("und", None, "VO", "en"),            # name fallback
    ("und", None, "VFF", "fr"),
    ("und", None, "VOSTFR", "fr"),        # French subtitles, not "VO"
    (None, None, "English SDH", "en"),
    ("und", None, "Français (forcés)", "fr"),
    ("ger", "de", "DE", None),            # not a configured language
    ("und", None, None, None),
])
def test_detect_lang(cfg, lang, ietf, name, expected):
    assert detect_lang(track(0, "audio", lang=lang, ietf=ietf, name=name), cfg) == expected


def test_language_tag_wins_over_name(cfg):
    assert detect_lang(track(0, "audio", lang="eng", ietf="en", name="FR"), cfg) == "en"


# --- text subtitles ----------------------------------------------------------------

SRT = """﻿1
00:00:01,000 --> 00:00:02,000
<i>Where's my car keys?</i>

2
00:00:03,000 --> 00:00:04,000
- Yeah.
- No way.

3
00:00:05,000 --> 00:00:06,000


4
00:00:07,000 --> 00:00:08,000
{\\an8}[LAUGHTER]
"""

VTT = """WEBVTT

NOTE this is a comment

00:01.000 --> 00:02.000
♪ Upbeat music ♪

cue-2
00:03.000 --> 00:04.000 align:start
MICHAEL: Honey!
"""

ASS = """[Script Info]
Title: test

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\i1}Hello, you{\\i0}
Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,(rires)\\NOui, bon.
Comment: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,not an event
"""


def test_parse_srt_strips_markup_and_skips_empty(tmp_path):
    p = tmp_path / "s.srt"
    p.write_text(SRT, encoding="utf-8")
    assert parse_text_events(p) == ["Where's my car keys?", "- Yeah.\n- No way.", "[LAUGHTER]"]


def test_parse_srt_with_crlf(tmp_path):
    p = tmp_path / "s.srt"
    p.write_bytes(SRT.replace("\n", "\r\n").encode("utf-8"))
    assert len(parse_text_events(p)) == 3


def test_parse_vtt_ignores_header_and_notes(tmp_path):
    p = tmp_path / "s.vtt"
    p.write_text(VTT, encoding="utf-8")
    assert parse_text_events(p) == ["♪ Upbeat music ♪", "MICHAEL: Honey!"]


def test_parse_ass_keeps_commas_in_text(tmp_path):
    p = tmp_path / "s.ass"
    p.write_text(ASS, encoding="utf-8")
    assert parse_text_events(p) == ["Hello, you", "(rires)\nOui, bon."]


@pytest.mark.parametrize("event, is_sdh", [
    ("[LAUGHTER]", True),
    ("[door slams] Hey!", True),
    ("(laughs)", True),
    ("(rires) Oui.", True),
    ("♪ La la la ♪", True),
    ("# Happy birthday #", True),
    ("MICHAEL: Where's my car keys?", True),
    ("- JAY: Honey!", True),
    ("Where's my car keys?", False),
    ("- Yeah.\n- No way.", False),
    ("Hey! (laughs)", True),
    ("- (sighs) Fine.", True),
    ("I paid $5 (or so) for it", False),   # parenthesis inside a sentence
    ("Okay: let's go.", False),            # not an upper-case label
])
def test_sdh_markers(event, is_sdh):
    assert any(m.search(event) for m in SDH_MARKERS) is is_sdh


def test_analyze_text_ratio(tmp_path):
    p = tmp_path / "s.srt"
    p.write_text(SRT, encoding="utf-8")
    assert analyze_text(p) == ContentStats(3, pytest.approx(1 / 3))


def test_analyze_text_empty_file(tmp_path):
    p = tmp_path / "s.srt"
    p.write_text("", encoding="utf-8")
    assert analyze_text(p) == ContentStats(0, 0.0)


# --- image subtitles ---------------------------------------------------------------

def pgs_stream(n_events: int) -> bytes:
    def seg(seg_type: int, payload: bytes) -> bytes:
        return b"PG" + struct.pack(">IIBH", 0, 0, seg_type, len(payload)) + payload
    one_set = seg(0x16, b"\x00" * 11) + seg(0x17, b"\x00" * 10) + seg(0x80, b"")
    return one_set * (2 * n_events)          # show + clear per event


def test_analyze_pgs(tmp_path):
    p = tmp_path / "s.sup"
    p.write_bytes(pgs_stream(42))
    assert analyze_pgs(p) == ContentStats(42)


def test_analyze_pgs_stops_on_garbage(tmp_path):
    p = tmp_path / "s.sup"
    p.write_bytes(pgs_stream(3) + b"garbage")
    assert analyze_pgs(p).events == 3


def test_analyze_vobsub(tmp_path):
    p = tmp_path / "s.idx"
    p.write_text("# VobSub index file\nsize: 720x480\nid: fr, index: 0\n"
                 "timestamp: 00:00:01:000, filepos: 000000000\n"
                 "timestamp: 00:00:05:000, filepos: 000000800\n", encoding="latin-1")
    assert analyze_vobsub(p) == ContentStats(2)


def test_analyzers_cover_all_subtitle_codecs():
    assert {a.extension for a in ANALYZERS.values()} == {"srt", "ass", "ssa", "vtt", "sup", "idx"}
