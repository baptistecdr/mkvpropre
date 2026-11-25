"""Tool invocation, remux safety, file discovery and titles."""
from __future__ import annotations

import logging
import stat
from pathlib import Path

import pytest

import mkvpropre
import mkvpropre.apply
import mkvpropre.cli
from mkvpropre.apply import remux
from mkvpropre.cli import find_files
from mkvpropre.model import Track
from mkvpropre.tools import ToolError, run_tool


def fake_tool(tmp_path: Path, exit_code: int, stdout: str = "", stderr: str = "") -> str:
    script = tmp_path / "fake-tool"
    script.write_text(f"#!/bin/sh\nprintf '%s' '{stdout}'\nprintf '%s' '{stderr}' >&2\nexit {exit_code}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


# --- run_tool ----------------------------------------------------------------------------

def test_run_tool_success_returns_stdout(tmp_path):
    assert run_tool([fake_tool(tmp_path, 0, stdout="{}")]) == "{}"


def test_run_tool_exit_1_is_warnings_only(tmp_path, caplog):
    tool = fake_tool(tmp_path, 1, stdout="ok", stderr="Warning: odd timestamps")
    with caplog.at_level(logging.WARNING):
        assert run_tool([tool]) == "ok"
    assert "Warning: odd timestamps" in caplog.text


def test_run_tool_exit_2_raises(tmp_path):
    with pytest.raises(ToolError, match="exit 2.*Error: disk full"):
        run_tool([fake_tool(tmp_path, 2, stdout="Error: disk full")])


# --- remux -------------------------------------------------------------------------------

def test_failed_remux_removes_temp_file_and_keeps_original(tmp_path, monkeypatch):
    episode = tmp_path / "Show.S01E01.mkv"
    episode.write_bytes(b"original")

    def failing_mkvmerge(cmd):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"partial")
        raise ToolError("mkvmerge failed (exit 2): disk full")

    monkeypatch.setattr(mkvpropre.apply, "run_tool", failing_mkvmerge)
    with pytest.raises(ToolError):
        remux(episode, [1, 0])
    assert episode.read_bytes() == b"original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Show.S01E01.mkv"]


def test_successful_remux_replaces_original(tmp_path, monkeypatch):
    episode = tmp_path / "Show.S01E01.mkv"
    episode.write_bytes(b"original")
    calls = []

    def mkvmerge(cmd):
        calls.append(cmd)
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"reordered")
        return ""

    monkeypatch.setattr(mkvpropre.apply, "run_tool", mkvmerge)
    remux(episode, [2, 0, 1])
    assert episode.read_bytes() == b"reordered"
    assert calls[0][calls[0].index("--track-order") + 1] == "0:2,0:0,0:1"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Show.S01E01.mkv"]


# --- files and titles --------------------------------------------------------------------

def test_find_files_skips_hidden_and_temp(tmp_path):
    for name in ["Show.S01E02.mkv", "Show.S01E01.mkv", "._Show.S01E01.mkv",
                 ".Show.S01E01.reorder.tmp.mkv", "x.reorder.tmp.mkv", "notes.txt"]:
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "Season 2").mkdir()
    (tmp_path / "Season 2" / "Show.S02E01.mkv").write_bytes(b"")
    found = [p.relative_to(tmp_path).as_posix() for p in find_files([tmp_path])]
    assert found == ["Season 2/Show.S02E01.mkv", "Show.S01E01.mkv", "Show.S01E02.mkv"]


def test_explicit_file_is_always_kept(tmp_path):
    f = tmp_path / ".hidden.mkv"
    assert find_files([f]) == [f]


# --- CLI -----------------------------------------------------------------------------------

@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version(flag, capsys, monkeypatch):
    # works without any path, and before the MKVToolNix / FileBot checks
    monkeypatch.setattr(mkvpropre.cli, "missing_tools", lambda: ["mkvmerge"])
    with pytest.raises(SystemExit) as exit_info:
        mkvpropre.cli.main([flag])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"mkvpropre {mkvpropre.__version__}"


def test_remux_removes_dropped_tracks(tmp_path, monkeypatch):
    episode = tmp_path / "Show.S01E01.mkv"
    episode.write_bytes(b"original")
    calls = []

    def mkvmerge(cmd):
        calls.append(cmd)
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"remuxed")
        return ""

    monkeypatch.setattr(mkvpropre.apply, "run_tool", mkvmerge)
    dropped = (Track(3, 4, "audio", "A_AC3", {}), Track(6, 7, "subtitles", "S_TEXT/UTF8", {}),
               Track(7, 8, "subtitles", "S_TEXT/UTF8", {}))
    remux(episode, [0, 1, 2, 5], dropped)
    cmd = calls[0]
    assert cmd[cmd.index("--audio-tracks") + 1] == "!3"
    assert cmd[cmd.index("--subtitle-tracks") + 1] == "!6,7"
    assert "--video-tracks" not in cmd
    assert cmd[cmd.index("--track-order") + 1] == "0:0,0:1,0:2,0:5"
    assert cmd.index("--audio-tracks") < cmd.index(str(episode))     # options apply to the input file
    assert {"--disable-track-statistics-tags", "--no-global-tags", "--no-track-tags"} <= set(cmd)
