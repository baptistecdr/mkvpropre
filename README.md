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

mkvpropre keeps the tracks you want, in this order, right after the video, and puts the rest at the end:

| # | Track | Name | Flags |
|---|---|---|---|
| 1 | Video | episode / movie title | default |
| 2 | Audio VO | `Anglais` | default, original |
| 3 | Audio French (VFF) | `Français` | |
| 4 | Subtitles VO | `Anglais` | original |
| 5 | Subtitles VO forced | `Anglais (forcés)` | forced, original |
| 6 | Subtitles French | `Français` | **default** |
| 7 | Subtitles French forced | `Français (forcés)` | forced |
| … | the rest | renamed: `Anglais (SDH)`, `Français (VFQ)`, `Français (AD)`, `Allemand`… | never default, at the end |

- Each line is filled with the best matching track: plain subtitles rather than SDH, France French (VFF) rather than
  Québec French (VFQ) or audio description, the main audio rather than a commentary, then the most audio channels.
  When the only French subtitles are SDH, or the only French audio is VFQ, that track is used.
- **The rest** is every other track: SDH next to plain subtitles, VFQ, audio description, commentaries, other
  languages. It's renamed with the same pattern, moved to the end and never default.
  **`--drop-other-tracks` removes it.**
- The VO is the original language from FileBot, so a Japanese film gets `Japonais` audio and subtitles first, and
  English becomes part of the rest.
- A film in **your native language** (French, `native` in `config.py`) only keeps its **forced** subtitles: you don't
  need full French subtitles for a French film. Its French lines are filled once, and English is the rest:

| # | Track | Name | Flags |
|---|---|---|---|
| 1 | Video | `Le Fabuleux Destin d'Amélie Poulain` | default |
| 2 | Audio French (VO) | `Français` | default, original |
| 3 | Subtitles French forced | `Français (forcés)` | **default**, forced, original |
| … | the rest: full / SDH French subtitles, English, VFQ, AD… | renamed | never default, at the end |

With `--drop-other-tracks`, a French film is left with the video, the French audio and the French forced subtitles.

On every track, the language is set both as a legacy code (`eng`, `fre`) and an IETF tag (`en`, `fr`, `fr-CA` for
VFQ), and the forced, original, commentary and hearing / visually impaired flags are set to match. The video track
gets the VO language. Attachments and tags are removed.

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

# Also remove the rest (SDH, VFQ, audio description, commentaries, other languages)
mkvpropre --drop-other-tracks "/media/raid/downloads/Amelie.2001.MULTI.1080p.BluRay.x264-GROUP"

# Normalize a download, then move it to the library
mkvpropre --library /media/raid/cinema "/media/raid/downloads/Amelie.2001.MULTI.1080p.BluRay.x264-GROUP"
```

### Options

| Option | Default | Description |
|---|---|---|
| `-V`, `--version` | | Print the installed version and exit |
| `--completion {bash,zsh,fish}` | | Print the shell completion script and exit (see [Shell completion](#shell-completion)) |
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
| `--original LANG` | from FileBot | Force the VO (`en`, `fr`, `ja`…) |
| `--drop-other-tracks` | | Remove the rest: every track the profile doesn't want (SDH next to plain subtitles, VFQ, audio description, commentaries, other languages) |
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

### Shell completion

mkvpropre prints its own completion script for bash, zsh and fish: options with their descriptions, the values of
`--original` and `--titles-db`, folders after `--library`, and `.mkv` files and folders for the paths.

```bash
# zsh: in ~/.zshrc, after compinit
eval "$(mkvpropre --completion zsh)"

# bash: in ~/.bashrc
eval "$(mkvpropre --completion bash)"

# fish
mkvpropre --completion fish > ~/.config/fish/completions/mkvpropre.fish
```

The script is generated from mkvpropre's options, so new options are completed after an update; regenerate the fish
file after updating.

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
- **Commentary** audio tracks (flag or name) are only used as the main audio when there is no other one.
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

### What counts as SDH, VFQ, audio description, commentary

- **SDH** subtitles: detected from their content (see above), or the hearing-impaired flag / name when the content
  can't tell;
- **Québec French (VFQ)**, audio and subtitles: tagged `fr-CA`, or named `VFQ`, `CA`, `Québécois`… when the tag has
  no region;
- **audio description**: the visually-impaired flag, or a name such as `AD`, `Audio Description`, `malvoyants`;
- **commentary**: the commentary flag, or "comment" in the name.

### Changing what you want

The wanted tracks are a plain list in [`mkvpropre/config.py`](mkvpropre/config.py), `PROFILE`:

```python
PROFILE = (
    Slot("audio", VO, default=True),
    Slot("audio", "fr", default=True),                        # default when there is no VO audio
    Slot("subtitles", VO, foreign_only=True),
    Slot("subtitles", VO, forced=True),
    Slot("subtitles", "fr", foreign_only=True, default=True),  # a French film doesn't need them
    Slot("subtitles", "fr", forced=True, default=True),        # so its forced ones are the default
)
```

- **Order**: the wanted tracks follow this order, right after the video.
- **`default`**: the first filled default slot of each kind is the default track: the VO audio, and the French full
  subtitles, or the French forced ones when there are no full ones (a French film).
- **`foreign_only`**: skipped for a film in your native language (`native = "fr"` in `Config`), so a French film
  keeps no full subtitles, only the forced ones.

Adding `Slot("audio", "en")` would always keep English audio too; removing `default=True` from the subtitle lines
would leave no subtitles on by default.
Track names come from the `LANGUAGES` table in the same file.

### --drop-other-tracks

Removes the rest, in the same lossless remux as the reordering. The dry run lists the tracks that would be removed.
When no wanted audio track exists at all (e.g. untagged `und` audio), the audio tracks are kept anyway, with a
warning, so a file never loses its sound.

### Safety

- The remux writes to a new temporary file with an unpredictable name next to the original, which is only replaced once
  `mkvmerge` has succeeded; the temporary file is always cleaned up.
- Download names are treated as untrusted: paths are always passed as absolute paths (a file named `-o.mkv` can't be
  read as an option), symlinks found in a folder are skipped, and names from TheMovieDB can't escape the library.
- MKVToolNix warnings (exit code 1) are shown but don't stop the file; errors (exit code 2) skip it.
- Running mkvpropre twice changes nothing the second time, and doesn't even touch the files' modification dates.

### Limitations

- Track names for languages outside the `LANGUAGES` table fall back to the language code (e.g. `KA`), and their
  language tags are left as they are.
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
  completion.py  shell completion scripts (--completion)
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
