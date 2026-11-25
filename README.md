# mkvpropre

Normalize MKV episodes and movies so every file looks the same in your player:
track order, track names, languages, default/forced/original/SDH flags, file
title. Attachments and tags are removed.

Everything is lossless: tracks are only reordered (a `mkvmerge` remux, no
re-encoding), all other changes are made in place with `mkvpropedit`. A file
that is already normalized is not touched at all.

*mkvpropre*: `mkvpropedit`, the tool doing most of the work, meets the French
*propre* ("clean"), which is how your files come out.

## Result

The VO (original language) always comes first. For a series or a movie in
English:

| # | Track | Name | Flags |
|---|---|---|---|
| 1 | Video | episode / movie title | default |
| 2 | Audio English (VO) | `Anglais` | default, original |
| 3 | Audio French | `Français` | |
| 4 | Subtitles English | `Anglais` | original |
| 5 | Subtitles English SDH | `Anglais (SDH)` | original, hearing impaired |
| 6 | Subtitles French | `Français` | **default** |
| 7 | Subtitles French forced | `Français (forcés)` | forced |
| … | any other track | unchanged | never default, moved to the end |

For a French movie or series, French comes first instead, and since full French
subtitles would only repeat the dialogue, the default subtitle track is the
French **forced** one (or none if there is no forced track):

| # | Track | Name | Flags |
|---|---|---|---|
| 1 | Video | `Le Fabuleux Destin d'Amélie Poulain` | default |
| 2 | Audio French (VO) | `Français` | default, original |
| 3 | Audio English | `Anglais` | |
| 4 | Subtitles French | `Français` | original |
| 5 | Subtitles French forced | `Français (forcés)` | **default**, forced |
| 6 | Subtitles English | `Anglais` | |

On every track, the language is set both as a legacy code (`eng`, `fre`) and an
IETF tag (`en`, `fr`), and unused flags (forced, commentary, visual / hearing
impaired) are explicitly cleared. The video track gets the VO language.

The file title and the video track name are set to the episode or movie title,
fetched from TheMovieDB through FileBot (in French by default).

## Requirements

- Python 3.11+
- [MKVToolNix](https://mkvtoolnix.download/): `mkvmerge`, `mkvextract`, `mkvpropedit`
- [FileBot](https://www.filebot.net/) for titles and VO detection (optional
  with `--no-filebot`). Only `filebot -list` is used, which works without a
  FileBot licence and never touches your files.

```bash
brew install mkvtoolnix
brew install --cask filebot
```

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

This installs the `mkvpropre` command in `.venv/bin/`. It can also be run
as `python -m mkvpropre`.

## Usage

Always start with a dry run: it prints what would be done (track decisions,
reordering, the exact `mkvpropedit` commands) without changing anything.

```bash
.venv/bin/mkvpropre --dry-run "/Volumes/Media/Series/My Wife And Kids"
```

Then apply it:

```bash
.venv/bin/mkvpropre "/Volumes/Media/Series/My Wife And Kids"
```

Folders are scanned recursively for `*.mkv` (hidden files such as macOS `._*`
are skipped). Files and folders can be mixed, and episodes and movies can be
processed in the same run.

### Examples

```bash
# A whole movie folder
.venv/bin/mkvpropre /Volumes/Media/Movies

# The file name is ambiguous: tell FileBot which show / movie it is
.venv/bin/mkvpropre --show "My Wife and Kids (2001)" "Season 1/"
.venv/bin/mkvpropre --movie "Dune (1984)" "Dune.mkv"

# English titles, from TheTVDB
.venv/bin/mkvpropre --titles-lang en --titles-db TheTVDB "My Wife And Kids/"

# No FileBot: titles left as they are, VO given by hand
.venv/bin/mkvpropre --no-filebot --original fr "Le Prénom.mkv"

# Only print warnings, errors and the summary
.venv/bin/mkvpropre -q /Volumes/Media
```

### Options

| Option | Default | Description |
|---|---|---|
| `-V`, `--version` | | Print the installed version and exit |
| `--dry-run` | | Show what would be done, change nothing |
| `-q`, `--quiet` | | Only print warnings and errors |
| **Title and VO** | | |
| `--show NAME` | from file / folder names | Series name for FileBot |
| `--movie "TITLE (YEAR)"` | from the file name | Movie for FileBot (applies to every movie file of the run) |
| `--titles-db DB` | `TheMovieDB::TV` | Series database: `TheMovieDB::TV`, `TheTVDB`, `TVmaze`… Movies always use TheMovieDB |
| `--titles-lang LANG` | `fr` | Title language |
| `--no-filebot` | | Don't use FileBot: titles left as is, VO from `--original` (default `en`) |
| **Languages** | | |
| `--original {en,fr}` | from FileBot | Force the VO |
| `--default-subs {en,fr,none}` | `fr` | Default subtitle language |
| **Forced / SDH detection** | | |
| `--no-content` | | Use only existing flags and track names |
| `--forced-ratio R` | `0.25` | Forced if it has fewer than R × the events of the fullest track of the same language |
| `--forced-per-min N` | `2.0` | Forced if it has fewer than N events per minute |
| `--sdh-ratio R` | `0.07` | SDH if at least R of its events look like SDH |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All files normalized (or already were) |
| `1` | Some files were skipped (see the summary) |
| `2` | MKVToolNix or FileBot is missing |

## How it works

### Identifying tracks

- **Language**: from the track's language tag (`eng`, `fre`, `fra`, `fr-CA`…);
  when it is missing or `und`, from the track name (`EN`, `VO`, `FR`, `VFF`,
  `VFQ`, `VOSTFR`, `TRUEFRENCH`…).
- **Commentary** audio tracks (flag or name) are not treated as main audio.
- **Forced and SDH subtitles** are detected from their **content**, not their
  (often wrong) names and flags:
  - *forced*: very few events compared with the other subtitle track of the
    same language, or fewer than 2 per minute when it is alone;
  - *SDH*: at least 7 % of the events contain sound descriptions (`[MUSIC]`,
    `(laughs)`, `(rires)`), music notes (`♪`) or speaker labels (`MICHAEL:`).

  Text subtitles (SRT, ASS/SSA, WebVTT) are extracted to analyse them. Image
  subtitles (PGS, VobSub) only get the forced check (from the number of
  events); for SDH, their flags and names are used. The dry run prints each
  verdict with the numbers behind it, and says when it disagrees with the
  existing flags.

### Title and VO (FileBot)

- **Episodes** (file name contains `SxxEyy`): the show name is the part of the
  file name before `SxxEyy` (release-group tags like `[Group]` removed), or the
  nearest folder that is not a season folder (`Season 1`, `Saison 02`, `S01`).
  The episode list is fetched once per show.
- **Movies** (no `SxxEyy`): the name and year are taken from the file name, up
  to the first release tag (`1080p`, `MULTI`, `BluRay`, `x264`…). A year in the
  title itself is kept: `Blade.Runner.2049.2017.mkv` → *Blade Runner 2049*
  (2017). A warning is printed when the file has no year, or when FileBot's
  match has a different year.
- The VO is FileBot's *original language* of the series or movie.

### Ambiguous files are skipped, not guessed

A file is skipped (and listed in the summary) when the script can't safely
decide, for example two French main audio tracks (VFF + VFQ), or two French
full subtitle tracks. Nothing is changed in that file.

### Safety

- The remux writes to a temporary file next to the original, which is only
  replaced once `mkvmerge` has succeeded; the temporary file is always cleaned
  up.
- MKVToolNix warnings (exit code 1) are shown but don't stop the file; errors
  (exit code 2) skip it.
- Running the script twice changes nothing the second time, and doesn't even
  touch the files' modification dates.

## Limitations

- Only **English** and **French** are handled as main languages. Tracks in
  other languages are kept, at the end, never default. If the VO is another
  language (e.g. Japanese), no track gets the *original* flag, the default
  audio falls back to English and the video language is left as it is.
- **Attachments are always removed**, fonts included: ASS/SSA subtitles that
  rely on embedded fonts will fall back to default fonts (a warning is printed).
- `--movie` applies to every movie file of the run: use it on one movie at a time.

## Development

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

The integration tests build small MKV files with `mkvmerge` and are skipped
when MKVToolNix is not installed. FileBot is never called by the tests (a fake
`filebot` script is used).

### Project layout

```
mkvpropre/
  config.py      languages, defaults, thresholds
  model.py       Track, MediaFile… (what a file contains)
  tools.py       running MKVToolNix
  subtitles.py   subtitle parsing and per-codec analysers
  probe.py       file -> MediaFile
  plan.py        MediaFile -> Plan (pure logic, no I/O)
  apply.py       Plan -> changes on disk
  lookup.py      title and VO with FileBot
  cli.py         command line
tests/           pytest suite
```

Per file, the pipeline is **probe → plan → apply**: `plan.py` decides the
target state of every track without touching anything, and `apply.py` only
sends `mkvpropedit` the properties that actually differ.
