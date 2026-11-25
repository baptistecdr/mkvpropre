<h3 align="center">mkvpropre</h3>
<p align="center">
    mkvpropre cleans up your MKV movies and series, losslessly: VO first, consistent track names, languages and flags,
    titles from TheMovieDB, and a tidy Plex / Jellyfin library.
    <br>
    <a href="https://github.com/baptistecdr/mkvpropre/issues/new">Report bug</a>
    ·
    <a href="https://github.com/baptistecdr/mkvpropre/issues/new">Request feature</a>
</p>

<div align="center">

![GitHub Tag](https://img.shields.io/github/v/tag/baptistecdr/mkvpropre?label=Latest%20version)

</div>

## Quick start

Install [MKVToolNix](https://mkvtoolnix.download/) and [FileBot](https://www.filebot.net/), then mkvpropre (Python
3.11+):

```bash
# macOS
brew install mkvtoolnix
brew install --cask filebot

# Debian / Ubuntu (FileBot: see https://www.filebot.net/linux/)
sudo apt install mkvtoolnix

# mkvpropre
uv tool install git+https://github.com/baptistecdr/mkvpropre    # or: pipx install git+https://…
```

Always start with a dry run: it prints what would be done (track decisions, reordering, the exact `mkvpropedit`
commands) without changing anything. Then run it for real:

```bash
mkvpropre --dry-run "/media/raid/downloads/My Wife And Kids.2001.INTEGRALE.MULTI.1080p.WEB.H265-FTMVHD"
mkvpropre "/media/raid/downloads/My Wife And Kids.2001.INTEGRALE.MULTI.1080p.WEB.H265-FTMVHD"
```

Everything is lossless: tracks are only reordered (a `mkvmerge` remux, no re-encoding), all other changes are made in
place with `mkvpropedit`, and a file that is already clean is not touched at all.

*mkvpropre*: `mkvpropedit`, the tool doing most of the work, meets the French *propre* ("clean"), which is how your
files come out.

## Result

The VO (original language) always comes first. For a series or a movie in English:

| # | Track | Name | Flags |
|---|---|---|---|
| 1 | Video | episode / movie title | default |
| 2 | Audio English (VO) | `Anglais` | default, original |
| 3 | Audio French | `Français` | |
| 4 | Subtitles English | `Anglais` | original |
| 5 | Subtitles English SDH | `Anglais (SDH)` | original, hearing impaired |
| 6 | Subtitles French | `Français` | **default** |
| 7 | Subtitles French forced | `Français (forcés)` | forced |
| … | any other track | unchanged | never default, moved to the end (or removed with `--drop-other-tracks`) |

For a French movie or series, French comes first instead, and since full French subtitles would only repeat the
dialogue, the default subtitle track is the French **forced** one (or none if there is no forced track):

| # | Track | Name | Flags |
|---|---|---|---|
| 1 | Video | `Le Fabuleux Destin d'Amélie Poulain` | default |
| 2 | Audio French (VO) | `Français` | default, original |
| 3 | Audio English | `Anglais` | |
| 4 | Subtitles French | `Français` | original |
| 5 | Subtitles French forced | `Français (forcés)` | **default**, forced |
| 6 | Subtitles English | `Anglais` | |

On every track, the language is set both as a legacy code (`eng`, `fre`) and an IETF tag (`en`, `fr`), and unused
flags (forced, commentary, visual / hearing impaired) are explicitly cleared. The video track gets the VO language.
Attachments and tags are removed.

The file title and the video track name are set to the episode or movie title, fetched from TheMovieDB through FileBot
(in French by default).

## Usage

Folders are scanned recursively for `*.mkv` (hidden files such as macOS `._*` and symlinks are skipped). Files and
folders can be mixed, and episodes and movies can be processed in the same run.

```bash
# A whole movie folder
mkvpropre /media/raid/downloads/movies

# The file name is ambiguous: tell FileBot which show / movie it is
mkvpropre --show "My Wife and Kids (2001)" "Season 1/"
mkvpropre --movie "Dune (1984)" "Dune.mkv"

# English titles, from TheTVDB
mkvpropre --titles-lang en --titles-db TheTVDB "My Wife And Kids/"

# No FileBot: titles left as they are, VO given by hand
mkvpropre --no-filebot --original fr "Le Prénom.mkv"

# Only print warnings, errors and the summary
mkvpropre -q /media/raid/downloads

# Also remove the other languages, commentaries and unknown tracks
mkvpropre --drop-other-tracks "/media/raid/downloads/Amelie.2001.MULTI.1080p.BluRay.x264-GROUP"

# Normalize a download, then move it to the library
mkvpropre --library /media/raid/cinema "/media/raid/downloads/Amelie.2001.MULTI.1080p.BluRay.x264-GROUP"
```

### Options

| Option | Default | Description |
|---|---|---|
| `-V`, `--version` | | Print the installed version and exit |
| `--dry-run` | | Show what would be done, change nothing |
| `--library DIR` | | Move normalized files to `DIR/movies` or `DIR/tvshows`, with English names |
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
| `--drop-other-tracks` | | Remove every track that isn't the video or English / French audio and subtitles (other languages, commentaries, unknown); the VO audio is always kept |
| **Forced / SDH detection** | | |
| `--no-content` | | Use only existing flags and track names |
| `--forced-ratio R` | `0.25` | Forced if it has fewer than R × the events of the fullest track of the same language |
| `--forced-per-min N` | `2.0` | Forced if it has fewer than N events per minute |
| `--sdh-ratio R` | `0.02` | SDH if at least R of its events look like SDH |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All files normalized (or already were) |
| `1` | Some files were skipped or not moved (see the summary) |
| `2` | MKVToolNix or FileBot is missing, or bad arguments |

## Moving to a library

With `--library DIR`, each file that was normalized successfully is moved into `DIR/movies` or `DIR/tvshows`, renamed
with **English** names following the Plex / Jellyfin conventions (the MKV title itself stays in `--titles-lang`):

```
/media/raid/cinema/
├── movies/
│   ├── Amélie (2001).mkv
│   ├── Mission - Impossible/                           ← sagas (TheMovieDB collections) get a folder
│   │   └── Mission - Impossible - Fallout (2018).mkv   ← "Mission: Impossible", ":" is not allowed
│   └── Star Wars/
│       ├── Star Wars (1977).mkv
│       └── The Empire Strikes Back (1980).mkv
└── tvshows/
    └── My Wife and Kids (2001)/
        └── Season 01/
            ├── My Wife and Kids (2001) - S01E01 - Pilot.mkv
            └── My Wife and Kids (2001) - S01E02 - The Truth Hurts.mkv
```

- English names come from a second FileBot query by TheMovieDB id, so they always match the same movie / show as the
  French title.
- Only files that went through without error are moved; the others stay in the download folder and are listed in the
  summary.
- An existing file in the library is never overwritten (the file is left where it is and reported).
- On the same file system the move is an instant rename; across file systems the file is copied, checked, then the
  original is deleted.
- `--dry-run` shows the destination of each file.
- Specials (season 0) go to a `Specials` folder.

## How it works

### Identifying tracks

- **Language**: from the track's language tag (`eng`, `fre`, `fra`, `fr-CA`…); when it is missing or `und`, from the
  track name (`EN`, `VO`, `FR`, `VFF`, `VFQ`, `VOSTFR`, `TRUEFRENCH`…).
- **Commentary** audio tracks (flag or name) are not treated as main audio.
- **Forced and SDH subtitles** are detected from their **content**, not their (often wrong) names and flags:
  - *forced*: very few events compared with the other subtitle track of the same language, or fewer than 2 per minute
    when it is alone;
  - *SDH*: at least 2 % of the events contain sound descriptions (`[MUSIC]`, `(laughs)`, `(rires)`), music notes
    (`♪`) or speaker labels (`MICHAEL:`). Regular subtitles score about 0 %, while some SDH tracks have only a few
    sound cues per episode (3 % on a real series).

  Text subtitles (SRT, ASS/SSA, WebVTT) are extracted to analyse them. Image subtitles (PGS, VobSub) only get the
  forced check (from the number of events); for SDH, their flags and names are used. The dry run prints each verdict
  with the numbers behind it, and says when it disagrees with the existing flags.

### Title and VO (FileBot)

Only `filebot -list` is used: it needs no FileBot licence and never touches your files.

- **Episodes** (file name contains `SxxEyy`): the show name is the part of the file name before `SxxEyy`
  (release-group tags like `[Group]` removed), or the nearest folder that is not a season folder (`Season 1`,
  `Saison 02`, `S01`). The episode list is fetched once per show.
- **Movies** (no `SxxEyy`): the name and year are taken from the file name, up to the first release tag (`1080p`,
  `MULTI`, `BluRay`, `x264`…). A year in the title itself is kept: `Blade.Runner.2049.2017.mkv` → *Blade Runner 2049*
  (2017). A warning is printed when the file has no year, or when FileBot's match has a different year.
- The VO is FileBot's *original language* of the series or movie.

### Removing other tracks

With `--drop-other-tracks`, every track that isn't the video or English / French audio and subtitles is removed
(in the same lossless remux as the reordering): other languages, commentaries, tracks with an unknown language.
Two kinds of track are always kept, with a warning:

- the audio in the VO language, e.g. the Japanese audio of a Japanese film (the VO isn't English or French, so its
  audio counts as an "other" track);
- any audio when the file has no English / French audio, so a file with untagged audio never loses its sound.

The dry run lists the tracks that would be removed.

### Ambiguous files are skipped, not guessed

A file is skipped (and listed in the summary) when mkvpropre can't safely decide, for example two French main audio
tracks (VFF + VFQ), or two French full subtitle tracks. Nothing is changed in that file.

### Safety

- The remux writes to a new temporary file with an unpredictable name next to the original, which is only replaced once
  `mkvmerge` has succeeded; the temporary file is always cleaned up.
- Download names are treated as untrusted: paths are always passed as absolute paths (a file named `-o.mkv` can't be
  read as an option), symlinks found in a folder are skipped, and names from TheMovieDB can't escape the library.
- MKVToolNix warnings (exit code 1) are shown but don't stop the file; errors (exit code 2) skip it.
- Running mkvpropre twice changes nothing the second time, and doesn't even touch the files' modification dates.

### Limitations

- Only **English** and **French** are handled as main languages. Tracks in other languages are kept, at the end, never
  default. If the VO is another language (e.g. Japanese), no track gets the *original* flag, the default audio falls
  back to English and the video language is left as it is.
- **Attachments are always removed**, fonts included: ASS/SSA subtitles that rely on embedded fonts will fall back to
  default fonts (a warning is printed).
- `--movie` applies to every movie file of the run: use it on one movie at a time.

## Development

```bash
git clone https://github.com/baptistecdr/mkvpropre && cd mkvpropre
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

The integration tests build small MKV files with `mkvmerge` and are skipped when MKVToolNix is not installed. FileBot is
never called by the tests (a fake `filebot` script is used).

```
mkvpropre/
  config.py      languages, defaults, thresholds
  model.py       Track, MediaFile… (what a file contains)
  tools.py       running MKVToolNix
  files.py       safe file operations (temp files, no-overwrite moves)
  subtitles.py   subtitle parsing and per-codec analysers
  probe.py       file -> MediaFile
  plan.py        MediaFile -> Plan (pure logic, no I/O)
  apply.py       Plan -> changes on disk
  lookup.py      title, VO and English names with FileBot
  library.py     library paths and safe moves (--library)
  cli.py         command line
tests/           pytest suite
```

Per file, the pipeline is **probe → plan → apply**: `plan.py` decides the target state of every track without touching
anything, and `apply.py` only sends `mkvpropedit` the properties that actually differ.

To release, bump `__version__` in `mkvpropre/__init__.py`, then push a matching tag (`git tag -a v0.2.0 && git push
origin v0.2.0`): the release workflow tests, builds and publishes the GitHub release.

## Bugs and feature requests

Have a bug or a feature request? Please first search for existing and closed issues. If your problem or idea is not
addressed yet, [please open a new issue](https://github.com/baptistecdr/mkvpropre/issues/new).

## Contributing

Contributions are welcome!

## Thanks to

- [MKVToolNix](https://mkvtoolnix.download/)
- [FileBot](https://www.filebot.net/)
- [TheMovieDB](https://www.themoviedb.org/)
