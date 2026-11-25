"""Decide the target state of a file. Pure logic: no I/O."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .config import NAME_SUFFIX, Config, Kind, Variant
from .model import ContentStats, MediaFile, Track

FORCED_NAME_RE = re.compile(r"forc[eé]s?|forced", re.I)
SDH_NAME_RE = re.compile(r"\b(sdh|cc|malentendants?|sourds)\b", re.I)
COMMENTARY_NAME_RE = re.compile(r"comment", re.I)


class PlanError(Exception):
    """The file is ambiguous; it is skipped rather than guessed at."""


@dataclass(frozen=True)
class TrackPlan:
    track: Track
    kind: Kind
    target: dict[str, str]   # mkvpropedit property -> wanted value

    def changes(self) -> dict[str, str]:
        return {k: v for k, v in self.target.items() if not same_text(self.track.current(k), v)}


def same_text(a: str, b: str) -> bool:
    # NFC: on macOS, mkvpropedit stores "ç" decomposed (c + combining cedilla).
    return unicodedata.normalize("NFC", a) == unicodedata.normalize("NFC", b)


@dataclass(frozen=True)
class Plan:
    media: MediaFile
    tracks: tuple[TrackPlan, ...]   # in target order
    title: str | None               # wanted file title, None = leave as is
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def order(self) -> list[int]:
        return [tp.track.id for tp in self.tracks]

    @property
    def needs_reorder(self) -> bool:
        return self.order != [t.id for t in self.media.tracks]

    def propedit_args(self) -> list[str]:
        """Only what differs from the file; empty = nothing to do."""
        args: list[str] = []
        if self.title is not None and not same_text(self.title, self.media.title):
            args += ["--edit", "info", "--set", f"title={self.title}"]
        for tp in self.tracks:
            changes = tp.changes()
            if changes:
                args += ["--edit", f"track:@{tp.track.number}"]
                for prop, value in changes.items():
                    args += ["--set", f"{prop}={value}"]
        for a in self.media.attachments:   # IDs as before this mkvpropedit call
            args += ["--delete-attachment", str(a.id)]
        if self.media.has_tags:
            args += ["--tags", "all:"]     # global + track tags
        return args


@dataclass(frozen=True)
class ContentVerdict:
    forced: bool | None   # None = unknown
    sdh: bool | None
    reason: str


def detect_lang(track: Track, cfg: Config) -> str | None:
    tag = (track.props.get("language_ietf") or track.props.get("language") or "und").lower()
    primary = tag.split("-")[0]
    for key, spec in cfg.langs.items():
        if primary in spec.codes:
            return key
    for key, spec in cfg.langs.items():
        if spec.name_pattern.search(track.name.strip()):
            return key
    return None


def content_verdicts(tracks: list[Track], media: MediaFile, cfg: Config) -> dict[int, ContentVerdict]:
    """Forced/SDH from content, for the subtitle tracks of one language."""
    stats = {t.id: media.content.get(t.id, ContentStats()) for t in tracks}
    counts = [s.events for s in stats.values() if s.events is not None]
    fullest = max(counts, default=0)
    minutes = media.minutes
    verdicts = {}
    for t in tracks:
        s = stats[t.id]
        forced, sdh, reasons = None, None, []
        if s.events is not None:
            per_min = s.events / minutes if minutes else None
            rel = s.events / fullest if fullest else None
            reason = f"{s.events} events"
            if per_min is not None:
                reason += f", {per_min:.1f}/min"
            if rel is not None and len(counts) > 1:
                reason += f", {rel:.0%} of fullest"
            reasons.append(reason)
            forced = (len(counts) > 1 and rel is not None and rel < cfg.forced_max_ratio) or \
                     (per_min is not None and per_min < cfg.forced_max_per_min)
        if s.sdh_ratio is not None:
            reasons.append(f"{s.sdh_ratio:.0%} SDH-like")
            sdh = s.sdh_ratio >= cfg.sdh_min_ratio
        verdicts[t.id] = ContentVerdict(forced, sdh, "; ".join(reasons) or "no content data")
    return verdicts


def metadata_variant(track: Track) -> Variant:
    if track.props.get("forced_track") or FORCED_NAME_RE.search(track.name):
        return Variant.FORCED
    if track.props.get("flag_hearing_impaired") or SDH_NAME_RE.search(track.name):
        return Variant.SDH
    return Variant.FULL


def decide_variant(verdict: ContentVerdict, meta: Variant) -> tuple[Variant, str]:
    """Content wins; flags/name fill in whatever the content can't tell."""
    if verdict.forced is None:
        return meta, "flags/name"
    if verdict.forced:
        return Variant.FORCED, "content"
    if verdict.sdh is not None:
        return (Variant.SDH if verdict.sdh else Variant.FULL), "content"
    # Not forced, but full vs SDH unknown (image subtitles).
    return (Variant.SDH if meta is Variant.SDH else Variant.FULL), "content for forced, flags/name for SDH"


def language_order(cfg: Config) -> list[str]:
    """VO first, then the other configured languages: ["fr", "en"] for a French film."""
    vo = [cfg.original] if cfg.original in cfg.langs else []
    return vo + [lang for lang in cfg.langs if lang != cfg.original]


def default_subtitle_variant(lang: str, groups: dict[Variant, list[Track]],
                             default_subs: str | None, default_audio: str | None) -> Variant | None:
    """Which subtitle track of `lang`, if any, is the default one.

    - `lang` is not the default subtitle language: none.
    - Same language as the default audio (e.g. a French film): full subtitles
      would repeat the dialogue, so only its forced track, if it has one.
    - Otherwise the full track, or the SDH one when there is no plain full track.
    """
    if lang != default_subs:
        return None
    if lang == default_audio:
        return Variant.FORCED if groups[Variant.FORCED] else None
    if groups[Variant.FULL]:
        return Variant.FULL
    return Variant.SDH if groups[Variant.SDH] else None


def make_plan(media: MediaFile, cfg: Config, title: str | None) -> Plan:
    notes: list[str] = []
    warnings: list[str] = []
    videos: list[Track] = []
    audio: dict[str, list[Track]] = {k: [] for k in cfg.langs}
    subs: dict[str, list[Track]] = {k: [] for k in cfg.langs}
    other: list[Track] = []

    for t in media.tracks:
        lang = detect_lang(t, cfg)
        if t.type == "video":
            videos.append(t)
        elif t.type == "audio" and lang and not (t.props.get("flag_commentary") or COMMENTARY_NAME_RE.search(t.name)):
            audio[lang].append(t)
        elif t.type == "subtitles" and lang:
            subs[lang].append(t)
        else:
            other.append(t)

    # Sanity checks
    if len(videos) != 1:
        warnings.append(f"{len(videos)} video tracks found")
    for lang, tracks in audio.items():
        if len(tracks) > 1:
            raise PlanError(f"{len(tracks)} '{lang}' audio tracks, can't tell which one is the main one: "
                            + ", ".join(t.describe() for t in tracks))
        if not tracks:
            warnings.append(f"no '{lang}' audio track")
    for lang, tracks in subs.items():
        if not tracks:
            warnings.append(f"no '{lang}' subtitle track")
    if other:
        warnings.append("unrecognised tracks kept at the end: " + ", ".join(t.describe() for t in other))
    if title is None:
        warnings.append("no episode title found, video track name and file title left as is")
    if any(a.is_font for a in media.attachments) and \
            any(t.codec in ("S_TEXT/ASS", "S_TEXT/SSA") for t in media.tracks):
        warnings.append("fonts will be removed while ASS/SSA subtitles are present: "
                        "their styling may fall back to default fonts")

    def lang_props(lang: str, name: str) -> dict[str, str]:
        spec = cfg.langs[lang]
        return {"name": name, "language": spec.iso639_2, "language-ietf": lang,
                "flag-original": str(int(lang == cfg.original))}

    plans: list[TrackPlan] = []

    # Video: language = VO (left as is when the VO isn't a configured language)
    for i, t in enumerate(videos):
        target = {"flag-default": str(int(i == 0)), "flag-forced": "0"}
        if cfg.original in cfg.langs:
            target |= {"language": cfg.langs[cfg.original].iso639_2, "language-ietf": cfg.original}
        if title:
            target["name"] = title
        plans.append(TrackPlan(t, Kind.VIDEO, target))

    # Audio and subtitles: VO first, then the other languages in configured order
    order = language_order(cfg)

    # Audio: the configured default language (the VO), else the first language present
    default_audio = cfg.default_audio if audio.get(cfg.default_audio) else \
        next((lang for lang in order if audio[lang]), None)
    if cfg.original not in cfg.langs:
        warnings.append(f"VO is '{cfg.original}', not one of {', '.join(cfg.langs)}: no track gets the "
                        f"original flag, and the default audio is '{default_audio}'")
    for lang in order:
        for t in audio[lang]:
            target = lang_props(lang, cfg.langs[lang].label) | {
                "flag-default": str(int(lang == default_audio)), "flag-forced": "0",
                "flag-commentary": "0", "flag-visual-impaired": "0"}
            plans.append(TrackPlan(t, Kind.AUDIO, target))

    # Subtitles: full, SDH, forced per language
    for lang in order:
        groups: dict[Variant, list[Track]] = {v: [] for v in Variant}
        verdicts = content_verdicts(subs[lang], media, cfg)
        for t in subs[lang]:
            meta = metadata_variant(t)
            variant, source = decide_variant(verdicts[t.id], meta)
            note = f"sub #{t.id} {t.name!r}: {variant.value} ({source}; {verdicts[t.id].reason})"
            if variant is not meta:
                note += f" — flags/name said {meta.value}"
            notes.append(note)
            groups[variant].append(t)
        for variant, tracks in groups.items():
            if len(tracks) > 1:
                raise PlanError(f"{len(tracks)} '{lang}' {variant.value} subtitle tracks: "
                                + ", ".join(t.describe() for t in tracks))
        default_variant = default_subtitle_variant(lang, groups, cfg.default_subs, default_audio)
        for variant in (Variant.FULL, Variant.SDH, Variant.FORCED):
            for t in groups[variant]:
                target = lang_props(lang, cfg.langs[lang].label + NAME_SUFFIX[variant]) | {
                    "flag-default": str(int(variant is default_variant)),
                    "flag-forced": str(int(variant is Variant.FORCED)),
                    "flag-hearing-impaired": str(int(variant is Variant.SDH))}
                plans.append(TrackPlan(t, Kind.SUBS, target))

    # Anything else: kept, never default
    for t in other:
        plans.append(TrackPlan(t, Kind.OTHER, {"flag-default": "0"}))

    return Plan(media, tuple(plans), title, tuple(notes), tuple(warnings))
