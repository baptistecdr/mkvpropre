"""Shell completion scripts (--completion)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import mkvpropre.cli
from mkvpropre.cli import build_parser
from mkvpropre.completion import SHELLS, generate, options
from mkvpropre.config import Config

PARSER = build_parser(Config())
ALL_OPTIONS = [s for a in PARSER._actions for s in a.option_strings]


def script(shell: str) -> str:
    return generate(PARSER, shell)


# --- every shell ---------------------------------------------------------------------------------

@pytest.mark.parametrize("shell", SHELLS)
def test_every_option_is_completed(shell):
    text = script(shell)
    for opt in ALL_OPTIONS:
        name = opt if shell != "fish" else (f"-l {opt[2:]}" if opt.startswith("--") else f"-s {opt[1:]}")
        assert name in text, f"{opt} missing from the {shell} script"


@pytest.mark.parametrize("shell", SHELLS)
def test_script_syntax(shell, tmp_path):
    if not shutil.which(shell):
        pytest.skip(f"{shell} not installed")
    f = tmp_path / f"completion.{shell}"
    f.write_text(script(shell), encoding="utf-8")
    res = subprocess.run([shell, "-n", str(f)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_options_metadata():
    by_name = {o.longs[0]: o for o in options(PARSER) if o.longs}
    assert by_name["--original"].words == ("en", "fr")
    assert by_name["--default-subs"].words == ("en", "fr", "none")
    assert by_name["--titles-db"].words == ("TheMovieDB::TV", "TheTVDB", "TVmaze")
    assert by_name["--library"].dirs and by_name["--library"].takes_value
    assert not by_name["--dry-run"].takes_value
    assert by_name["--show"].takes_value and not by_name["--show"].words
    assert "%(" not in "".join(o.help for o in options(PARSER))         # defaults expanded


def test_zsh_escapes_special_characters():
    text = script("zsh")
    assert r"TheMovieDB\:\:TV" in text                                  # ":" separates _arguments fields
    assert "program'\\''s version" in text                              # quote inside '...'


def test_unknown_shell():
    with pytest.raises(ValueError, match="unsupported shell"):
        generate(PARSER, "powershell")


# --- real bash completion ------------------------------------------------------------------------

def complete_bash(tmp_path: Path, *words: str, comp_words: tuple[str, ...] | None = None) -> list[str]:
    """What bash offers for `mkvpropre <words>` (the last word is the one being completed).

    `comp_words`: COMP_WORDS as bash splits them, when it differs from `words` (":" splits words).
    """
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not installed")
    f = tmp_path / "completion.bash"
    f.write_text(script("bash"), encoding="utf-8")
    split = ("mkvpropre", *(comp_words or words))
    words_array = " ".join("'" + w.replace("'", "'\\''") + "'" for w in split)
    line = " ".join(("mkvpropre", *words)).replace("'", "'\\''")
    code = (f"source '{f}'; COMP_WORDS=({words_array}); COMP_CWORD={len(split) - 1}; "
            f"COMP_LINE='{line}'; COMP_POINT=${{#COMP_LINE}}; "
            "_mkvpropre; printf '%s\\n' \"${COMPREPLY[@]}\"")
    res = subprocess.run([bash, "--norc", "--noprofile", "-c", code], capture_output=True, text=True,
                         cwd=tmp_path, check=True)
    return sorted(line for line in res.stdout.splitlines() if line)


@pytest.fixture
def media_dir(tmp_path):
    (tmp_path / "Amelie 2001.mkv").write_bytes(b"")
    (tmp_path / "OTHER.MKV").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")
    (tmp_path / "Season 1").mkdir()
    (tmp_path / "cinema").mkdir()
    return tmp_path


def test_bash_choices(tmp_path):
    assert complete_bash(tmp_path, "--original", "") == ["en", "fr"]
    assert complete_bash(tmp_path, "--default-subs", "n") == ["none"]
    assert complete_bash(tmp_path, "--titles-db", "TheT") == ["TheTVDB"]


def test_bash_values_with_colons(tmp_path):
    # bash splits "TheMovieDB::" into "TheMovieDB" "::" "": the value is rebuilt from the line,
    # and only what follows the last ":" is offered (bash already has the rest)
    assert complete_bash(tmp_path, "--titles-db", "TheMovieDB::",
                         comp_words=("--titles-db", "TheMovieDB", "::", "")) == ["TV"]
    assert complete_bash(tmp_path, "--titles-db", "TheMovieDB::T",
                         comp_words=("--titles-db", "TheMovieDB", "::", "T")) == ["TV"]
    assert complete_bash(tmp_path, "--titles-db", "TheM") == ["TheMovieDB::TV"]


def test_bash_options(tmp_path):
    assert complete_bash(tmp_path, "--dr") == ["--drop-other-tracks", "--dry-run"]
    assert complete_bash(tmp_path, "-") == sorted(ALL_OPTIONS)


def test_bash_library_offers_folders_only(media_dir):
    assert complete_bash(media_dir, "--library", "") == ["Season 1", "cinema"]
    assert complete_bash(media_dir, "--library", "ci") == ["cinema"]


def test_bash_paths_are_mkv_files_and_folders(media_dir):
    assert complete_bash(media_dir, "") == ["Amelie 2001.mkv", "OTHER.MKV", "Season 1", "cinema"]
    assert complete_bash(media_dir, "--dry-run", "Am") == ["Amelie 2001.mkv"]


def test_bash_free_values_offer_nothing(tmp_path):
    assert complete_bash(tmp_path, "--show", "") == []


# --- CLI -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("shell", SHELLS)
def test_cli_prints_script_without_paths_or_tools(shell, capsys, monkeypatch):
    monkeypatch.setattr(mkvpropre.cli, "missing_tools", lambda: ["mkvmerge"])
    with pytest.raises(SystemExit) as exit_info:
        mkvpropre.cli.main(["--completion", shell])
    assert exit_info.value.code == 0
    out = capsys.readouterr()
    assert out.out == script(shell) and out.err == ""                   # stdout, for eval "$(...)"


def test_cli_rejects_unknown_shell(capsys):
    with pytest.raises(SystemExit) as exit_info:
        mkvpropre.cli.main(["--completion", "powershell"])
    assert exit_info.value.code == 2
