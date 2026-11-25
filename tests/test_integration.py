"""End to end with the real MKVToolNix tools on a small generated file."""
from __future__ import annotations

import logging
import shutil
import subprocess
import unicodedata
from pathlib import Path

import pytest

from normalize_mkv.config import Config
from normalize_mkv.tools import ToolError
from normalize_mkv.probe import read_media
from normalize_mkv.apply import process

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not all(shutil.which(t) for t in ("mkvmerge", "mkvextract", "mkvpropedit")),
                       reason="MKVToolNix not installed"),
]


def write_srt(path: Path, lines: list[str], span_s: float = 1200) -> Path:
    def ts(s: float) -> str:
        return f"{int(s // 3600):02}:{int(s % 3600 // 60):02}:{int(s % 60):02},{int(s * 1000 % 1000):03}"
    blocks = []
    for i, text in enumerate(lines):
        start = 5 + i * span_s / len(lines)
        blocks.append(f"{i + 1}\n{ts(start)} --> {ts(start + 2)}\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


@pytest.fixture
def episode(tmp_path: Path) -> Path:
    """Subtitle-only MKV: shuffled order, misleading names/flags, attachments, global tags."""
    plain_en = ["Where's my car keys?", "- Yeah.\n- No way.", "Junior, get down here!"]
    plain_fr = ["Où sont mes clés ?", "- Oui.\n- Pas question.", "Junior, descends !"]
    sdh = ["[LAUGHTER]", "♪ Upbeat music ♪", "MICHAEL: Honey!"]
    fr_forced = write_srt(tmp_path / "fr_forced.srt", ["Parle espagnol"] * 6)
    en_full = write_srt(tmp_path / "en_full.srt", [plain_en[i % 3] for i in range(200)])
    fr_full = write_srt(tmp_path / "fr_full.srt", [plain_fr[i % 3] for i in range(190)])
    en_sdh = write_srt(tmp_path / "en_sdh.srt",
                       [sdh[i % 3] if i % 5 == 0 else plain_en[i % 3] for i in range(230)])
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    tags = tmp_path / "tags.xml"
    tags.write_text('<?xml version="1.0"?><Tags><Tag><Targets/><Simple><Name>COMMENT</Name>'
                    "<String>release group</String></Simple></Tag></Tags>", encoding="utf-8")

    out = tmp_path / "media" / "Show.S01E01.mkv"
    out.parent.mkdir()
    subprocess.run([
        "mkvmerge", "-q", "-o", str(out), "--title", "Show.S01E01.MULTI.1080p.WEB-GROUP",
        "--global-tags", str(tags), "--attachment-mime-type", "image/jpeg", "--attach-file", str(cover),
        "--language", "0:fre", "--track-name", "0:FR", "--default-track-flag", "0:1", str(fr_forced),
        "--language", "0:eng", "--track-name", "0:Track 2", str(en_full),
        "--language", "0:fre", "--track-name", "0:FR Forced", "--forced-display-flag", "0:1", str(fr_full),
        "--language", "0:eng", "--track-name", "0:Track 4", str(en_sdh),
    ], check=True)
    return out


def run(path: Path, dry: bool, caplog) -> tuple[bool, list[str]]:
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="normalize_mkv"):
        changed = process(path, Config(), "Pilot", dry)
    return changed, [r.getMessage() for r in caplog.records]


def test_normalize_end_to_end(episode, caplog):
    before = episode.read_bytes()

    dry_changed, dry_log = run(episode, True, caplog)
    assert dry_changed
    assert episode.read_bytes() == before, "--dry-run must not touch the file"

    changed, real_log = run(episode, False, caplog)
    assert changed
    assert real_log == dry_log, "--dry-run must print exactly what the real run does"

    media = read_media(episode)
    assert media.title == "Pilot"
    assert media.attachments == ()
    assert not media.has_tags
    subs = [(t.name, t.current("language"), t.current("flag-default"), t.current("flag-forced"),
             t.current("flag-hearing-impaired"), t.current("flag-original")) for t in media.tracks]
    # mkvpropedit stores names decomposed on macOS: compare in NFC
    assert [(unicodedata.normalize("NFC", n), *rest) for n, *rest in subs] == [
        ("Anglais", "eng", "0", "0", "0", "1"),
        ("Anglais (SDH)", "eng", "0", "0", "1", "1"),
        ("Français", "fre", "1", "0", "0", "0"),
        ("Français (forcés)", "fre", "0", "1", "0", "0"),
    ]
    assert list(episode.parent.iterdir()) == [episode], "no temp file left behind"


def test_second_run_changes_nothing(episode, caplog):
    run(episode, False, caplog)
    mtime = episode.stat().st_mtime_ns
    changed, log = run(episode, False, caplog)
    assert not changed
    assert "   already normalized" in log
    assert episode.stat().st_mtime_ns == mtime


def test_not_an_mkv(tmp_path):
    bogus = tmp_path / "Show.S01E01.mkv"
    bogus.write_text("not a video")
    with pytest.raises(ToolError):
        process(bogus, Config(), None, dry=False)
