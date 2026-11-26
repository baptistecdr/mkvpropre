"""Languages, the profile of wanted tracks, defaults and detection thresholds."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum


# --- Languages -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Language:
    code: str                                  # ISO 639-1, the IETF primary subtag: "en"
    iso639_2: str                              # legacy "language" element: "eng"
    label: str                                 # track name (in French): "Anglais"
    aliases: frozenset[str] = frozenset()      # other tags meaning this language: "eng"
    name_pattern: re.Pattern[str] | None = None  # track names meaning it, when the tag is missing / "und"


def _lang(code: str, iso639_2: str, label: str, *aliases: str, names: str | None = None) -> Language:
    return Language(code, iso639_2, label, frozenset({iso639_2, *aliases}),
                    re.compile(names, re.I) if names else None)


LANGUAGES: dict[str, Language] = {lang.code: lang for lang in (
    _lang("en", "eng", "Anglais", names=r"^(en|eng|english|anglais|vo)\b"),
    _lang("fr", "fre", "Français", "fra",
          names=r"^(fr|fre|fra|french|fran[cç]ais|vf[fqi]?|vostfr|truefrench)\b"),
    _lang("de", "ger", "Allemand", "deu"),
    _lang("es", "spa", "Espagnol"),
    _lang("it", "ita", "Italien"),
    _lang("pt", "por", "Portugais"),
    _lang("nl", "dut", "Néerlandais", "nld"),
    _lang("ja", "jpn", "Japonais"),
    _lang("ko", "kor", "Coréen"),
    _lang("zh", "chi", "Chinois", "zho"),
    _lang("ru", "rus", "Russe"),
    _lang("pl", "pol", "Polonais"),
    _lang("sv", "swe", "Suédois"),
    _lang("da", "dan", "Danois"),
    _lang("no", "nor", "Norvégien", "nob", "nno", "nb", "nn"),
    _lang("fi", "fin", "Finnois"),
    _lang("cs", "cze", "Tchèque", "ces"),
    _lang("hu", "hun", "Hongrois"),
    _lang("el", "gre", "Grec", "ell"),
    _lang("tr", "tur", "Turc"),
    _lang("ar", "ara", "Arabe"),
    _lang("he", "heb", "Hébreu"),
    _lang("hi", "hin", "Hindi"),
    _lang("th", "tha", "Thaï"),
    _lang("uk", "ukr", "Ukrainien"),
    _lang("ro", "rum", "Roumain", "ron"),
    _lang("und", "und", "Inconnu"),
)}


def find_language(tag: str | None) -> Language | None:
    """'en', 'eng', 'en-US' -> English; None for an empty or unknown tag."""
    primary = (tag or "").strip().lower().replace("_", "-").split("-")[0]
    if not primary:
        return None
    return next((lang for lang in LANGUAGES.values() if primary == lang.code or primary in lang.aliases), None)


def language_label(code: str) -> str:
    lang = find_language(code)
    return lang.label if lang else code.upper()


# --- The tracks you want (the profile) -------------------------------------------------------

VO = "vo"   # stands for the original language of the movie / series (from FileBot or --original)


@dataclass(frozen=True)
class Slot:
    """One wanted track. The best matching track of the file fills it (see plan.rank)."""
    kind: str                   # "audio" or "subtitles"
    lang: str                   # language code, or VO
    forced: bool = False        # subtitles: the forced track rather than the full one
    default: bool = False       # the first filled default slot of each kind is the default track
    foreign_only: bool = False  # only for a film that isn't in your native language (Config.native)


# Kept in this order, right after the video. Anything else is "the rest": renamed, moved to
# the end, never default, and removed with --drop-other-tracks. When the VO is French, the
# French slots are the VO ones and are only filled once.
PROFILE: tuple[Slot, ...] = (
    Slot("audio", VO, default=True),
    Slot("audio", "fr", default=True),                        # default when there is no VO audio
    Slot("subtitles", VO, foreign_only=True),
    Slot("subtitles", VO, forced=True),
    Slot("subtitles", "fr", foreign_only=True, default=True),  # a French film doesn't need them
    Slot("subtitles", "fr", forced=True, default=True),        # so its forced ones are the default
)


@dataclass(frozen=True)
class Config:
    profile: tuple[Slot, ...] = PROFILE
    original: str = "en"             # VO (ISO 639-1): first audio, default audio, "original" flag
    native: str = "fr"               # your language: skips the foreign_only slots for a film in it
    use_content: bool = True         # analyse subtitle content for forced/SDH
    drop_other: bool = False         # remove the rest (tracks the profile doesn't want)
    forced_max_ratio: float = 0.25   # forced if < 25% of the fullest same-language track
    forced_max_per_min: float = 2.0  # or < 2 events per minute
    # SDH if >= 2% of events look like SDH. Regular subtitles score ~0% (112/112
    # French tracks of a real series), light SDH tracks as little as 3%.
    sdh_min_ratio: float = 0.02

    def with_original(self, lang: str) -> Config:
        return replace(self, original=lang)


class Kind(Enum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBS = "subtitles"
    REST = "rest"       # tracks the profile doesn't want


class Variant(Enum):
    FULL = "full"
    SDH = "sdh"
    FORCED = "forced"
