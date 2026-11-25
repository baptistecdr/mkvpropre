"""Languages, defaults and detection thresholds."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum


@dataclass(frozen=True)
class LangSpec:
    codes: frozenset[str]          # language tags that mean this language
    name_pattern: re.Pattern[str]  # track names that mean this language (fallback)
    iso639_2: str                  # value for the legacy "language" element
    label: str                     # track name to set


LANGS: dict[str, LangSpec] = {
    "en": LangSpec(frozenset({"en", "eng"}),
                   re.compile(r"^(en|eng|english|anglais|vo)\b", re.I), "eng", "Anglais"),
    "fr": LangSpec(frozenset({"fr", "fre", "fra"}),
                   re.compile(r"^(fr|fre|fra|french|fran[cç]ais|vf[fqi]?|vostfr|truefrench)\b", re.I),
                   "fre", "Français"),
}


@dataclass(frozen=True)
class Config:
    langs: dict[str, LangSpec] = field(default_factory=lambda: dict(LANGS))
    original: str = "en"             # VO (ISO 639-1): video language, "original" flag, default audio
    default_audio: str = "en"
    default_subs: str | None = "fr"  # None: no default subtitles (forced tracks excepted, see plan)
    use_content: bool = True         # analyse subtitle content for forced/SDH
    drop_other: bool = False         # remove tracks that aren't video / EN / FR (VO audio is always kept)
    forced_max_ratio: float = 0.25   # forced if < 25% of the fullest same-language track
    forced_max_per_min: float = 2.0  # or < 2 events per minute
    # SDH if >= 2% of events look like SDH. Regular subtitles score ~0% (112/112
    # French tracks of a real series), light SDH tracks as little as 3%.
    sdh_min_ratio: float = 0.02

    def with_original(self, lang: str) -> Config:
        """VO = `lang`: it gets the "original" flag and becomes the default audio.

        A VO outside `langs` (e.g. "ja") still clears the "original" flag of the
        other languages; the default audio then falls back to `default_audio`.
        """
        default_audio = lang if lang in self.langs else self.default_audio
        return replace(self, original=lang, default_audio=default_audio)


class Kind(Enum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBS = "subtitles"
    OTHER = "other"


class Variant(Enum):
    FULL = "full"
    SDH = "sdh"
    FORCED = "forced"


NAME_SUFFIX = {Variant.FULL: "", Variant.SDH: " (SDH)", Variant.FORCED: " (forcés)"}
