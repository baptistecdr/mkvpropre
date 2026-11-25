"""Normalize MKV episodes and movies: track order, names, languages and flags.

Target layout, VO first (here an English VO; a French film swaps EN and FR):
  1. Video                      name = episode / movie title, default
  2. Audio VO (English)         "Anglais",  default, original
  3. Audio French               "Français"
  4. Subs VO (English)          "Anglais"   (+ SDH / forced variants)
  5. Subs French                "Français", default (+ SDH / forced variants)
  ...any other tracks are kept, moved to the end, never default.

The VO (original language) comes first, gets the "original" flag and is the
default audio.
Default subtitles: the French full track, unless the VO itself is French; then
only the French forced track (if any) is default, since full French subtitles
would just repeat the dialogue.

Tracks are identified by their language tag, falling back to the track name
("EN", "VO", "FR", "VFF", ...) when the tag is missing or "und".

Forced and SDH subtitles are detected from their content (number of events,
sound descriptions / music notes / speaker labels); flags and track names are
only used when the content can't tell (e.g. SDH on image subtitles).

All attachments (fonts, covers, ...) and all tags, global and per-track, are
removed. A file that already matches is not touched.

Title and VO come from FileBot (`filebot -list`, no licence needed):
  episodes   file name with SxxEyy: the show's episode list, fetched once per
             show; show name from the file name (before SxxEyy) or its folder
  movies     anything else: TheMovieDB, queried with the name and year found
             in the file name
--show / --movie override the detected names, --original the VO.

Exit code: 0 all files ok, 1 some files skipped, 2 missing tools.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from .apply import process
from .config import LANGS, Config
from .lookup import FileInfo, Lookup, filebot_available
from .plan import PlanError
from .tools import ToolError, missing_tools

log = logging.getLogger(__name__)


def find_files(paths: list[Path]) -> list[Path]:
    def wanted(p: Path) -> bool:
        # skip hidden files: macOS "._" resource forks and our own temp files
        return not p.name.startswith(".") and not p.name.endswith(".tmp.mkv")
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files += sorted(f for f in p.rglob("*.mkv") if wanted(f))
        else:
            files.append(p)
    return files


def file_config(cfg: Config, info: FileInfo, original: str | None) -> tuple[Config, str]:
    """This file's config: VO from --original, else FileBot, else the default (en)."""
    if original:
        return cfg.with_original(original), "--original"
    if info.original:
        return cfg.with_original(info.original), info.source
    return cfg, info.source or "no FileBot match"


def parse_args(argv: list[str] | None, defaults: Config) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="mkvpropre", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path, metavar="FILE_OR_DIR")
    ap.add_argument("--dry-run", action="store_true", help="show what would be done, change nothing")

    t = ap.add_argument_group("title and VO (FileBot)")
    t.add_argument("--show", help='series name for FileBot, e.g. "My Wife and Kids (2001)" '
                                  "(default: from the file or folder names)")
    t.add_argument("--movie", help='movie for FileBot, e.g. "Amélie (2001)" (default: from the file name; '
                                   "applies to every movie file given)")
    t.add_argument("--titles-db", default="TheMovieDB::TV",
                   help="series database: TheMovieDB::TV, TheTVDB, TVmaze, ... (default %(default)s); "
                        "movies always use TheMovieDB")
    t.add_argument("--titles-lang", default="fr", help="title language (default %(default)s)")
    t.add_argument("--no-filebot", action="store_true",
                   help="don't use FileBot: titles left as is, VO from --original (default en)")

    lg = ap.add_argument_group("languages")
    lg.add_argument("--original", choices=sorted(LANGS),
                    help="VO, instead of FileBot's original language")
    lg.add_argument("--default-subs", choices=[*sorted(LANGS), "none"], default=defaults.default_subs,
                    help="default subtitle language (default %(default)s)")

    c = ap.add_argument_group("forced / SDH detection")
    c.add_argument("--no-content", action="store_true",
                   help="detect forced/SDH subtitles from flags and track names only")
    c.add_argument("--forced-ratio", type=float, default=defaults.forced_max_ratio,
                   help="forced if events < this share of the fullest same-language track "
                        f"(default {defaults.forced_max_ratio})")
    c.add_argument("--forced-per-min", type=float, default=defaults.forced_max_per_min,
                   help=f"forced if fewer events per minute than this (default {defaults.forced_max_per_min})")
    c.add_argument("--sdh-ratio", type=float, default=defaults.sdh_min_ratio,
                   help=f"SDH if at least this share of events look like SDH (default {defaults.sdh_min_ratio})")
    ap.add_argument("-q", "--quiet", action="store_true", help="only print warnings and errors")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    defaults = Config()
    args = parse_args(argv, defaults)
    logging.basicConfig(format="%(message)s", level=logging.WARNING if args.quiet else logging.INFO)

    missing = missing_tools()
    if missing:
        log.error("missing MKVToolNix tools: %s (brew install mkvtoolnix)", ", ".join(missing))
        return 2
    if not args.no_filebot and not filebot_available():
        log.error("missing FileBot, needed for titles and VO (brew install --cask filebot), "
                  "or run with --no-filebot")
        return 2

    cfg = replace(defaults, use_content=not args.no_content, forced_max_ratio=args.forced_ratio,
                  forced_max_per_min=args.forced_per_min, sdh_min_ratio=args.sdh_ratio,
                  default_subs=None if args.default_subs == "none" else args.default_subs)
    files = find_files(args.paths)
    lookup = Lookup(db=args.titles_db, lang=args.titles_lang, show=args.show, movie=args.movie)
    if not args.no_filebot:
        lookup.prepare(files)

    changed, failed = 0, []
    for f in files:
        info = FileInfo() if args.no_filebot else lookup.info_for(f)
        file_cfg, source = file_config(cfg, info, args.original)
        try:
            changed += process(f, file_cfg, info.title, args.dry_run, source)
        except (PlanError, ToolError, OSError, ValueError) as e:
            log.error("   ✗ skipped: %s", e)
            failed.append(f)

    verb = "would change" if args.dry_run else "changed"
    log.warning("\nDone: %d file(s), %d %s, %d unchanged, %d skipped",
                len(files), changed, verb, len(files) - changed - len(failed), len(failed))
    for f in failed:
        log.warning("   - %s", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
