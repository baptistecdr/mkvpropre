"""Decide the target state of a file. Pure logic: no I/O.

The profile (config.PROFILE) lists the wanted tracks, in order: VO audio, French
audio, VO subtitles, VO forced, French subtitles, French forced. Each slot is
filled with the best matching track (rank: the plain track first, then variants);
everything else is "the rest": renamed, moved to the end, never default, and
removed with --drop-other-tracks.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .config import VO, Config, Kind, Slot, Variant, find_language, language_label
from .model import ContentStats, MediaFile, Track

FORCED_NAME_RE = re.compile(r"forc[eé]s?|forced", re.I)
SDH_NAME_RE = re.compile(r"\b(sdh|cc|malentendants?|sourds)\b", re.I)
COMMENTARY_NAME_RE = re.compile(r"comment", re.I)
# Québec French (VFQ): "fr-CA" tag, or the name when there is no region in the tag
QUEBEC_NAME_RE = re.compile(r"\b(ca|vfq|qu[ée]b[ée]c(ois)?|canad\w*|qc)\b", re.I)
# Audio description (narration for the visually impaired)
AD_NAME_RE = re.compile(r"\b(ad|audio[ -]?descri\w*|descri\w*[ -]audio|visually[ -]impaired|malvoyants?)\b", re.I)


def is_quebec(track: Track) -> bool:
    tag = (track.props.get("language_ietf") or "").lower()
    if tag.startswith("fr-"):
        return tag == "fr-ca"
    return bool(QUEBEC_NAME_RE.search(track.name))


def is_audio_description(track: Track) -> bool:
    return bool(track.props.get("flag_visual_impaired")) or bool(AD_NAME_RE.search(track.name))


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
    tracks: tuple[TrackPlan, ...]   # kept tracks, in target order
    title: str | None               # wanted file title, None = leave as is
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    dropped: tuple[Track, ...] = () # the rest, removed with --drop-other-tracks

    @property
    def order(self) -> list[int]:
        return [tp.track.id for tp in self.tracks]

    @property
    def needs_remux(self) -> bool:
        """Tracks to reorder or to remove: both need a (lossless) mkvmerge remux."""
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


# --- Candidates: audio and subtitle tracks, as the profile sees them ----------------------------

def detect_lang(track: Track) -> str:
    """Language code of a track: from its tag, else from its name ("VF", "VOSTFR"...), else "und"."""
    tag = track.props.get("language_ietf") or track.props.get("language") or ""
    lang = find_language(tag)
    if lang and lang.code != "und":
        return lang.code
    primary = tag.lower().split("-")[0]
    if primary and primary != "und":
        return primary                       # a language mkvpropre has no label for
    for lang in (find_language("en"), find_language("fr")):
        if lang and lang.name_pattern and lang.name_pattern.search(track.name.strip()):
            return lang.code
    return "und"


@dataclass(frozen=True)
class Candidate:
    track: Track
    lang: str
    forced: bool = False       # subtitles
    sdh: bool = False          # subtitles
    quebec: bool = False       # French tracks
    ad: bool = False           # audio description
    commentary: bool = False   # audio

    @property
    def kind(self) -> str:
        return self.track.type


def rank(c: Candidate) -> tuple:
    """Lower is better: the plain track first, then its variants, then the richest audio, then file order."""
    return (c.commentary, c.ad, c.quebec, c.sdh, -int(c.track.props.get("audio_channels") or 0), c.track.id)


def matches(c: Candidate, slot: Slot, lang: str) -> bool:
    return c.kind == slot.kind and c.lang == lang and (c.kind == "audio" or c.forced == slot.forced)


def candidates(media: MediaFile, cfg: Config, notes: list[str]) -> list[Candidate]:
    langs = {t.id: detect_lang(t) for t in media.tracks}
    subs_by_lang: dict[str, list[Track]] = {}
    for t in media.tracks:
        if t.type == "subtitles":
            subs_by_lang.setdefault(langs[t.id], []).append(t)
    variants: dict[int, Variant] = {}
    for tracks in subs_by_lang.values():
        verdicts = content_verdicts(tracks, media, cfg)
        for t in tracks:
            meta = metadata_variant(t)
            variant, source = decide_variant(verdicts[t.id], meta)
            note = f"sub #{t.id} {t.name!r}: {variant.value} ({source}; {verdicts[t.id].reason})"
            notes.append(note + (f" — flags/name said {meta.value}" if variant is not meta else ""))
            variants[t.id] = variant

    result = []
    for t in media.tracks:
        if t.type not in ("audio", "subtitles"):
            continue
        lang = langs[t.id]
        result.append(Candidate(
            t, lang,
            forced=variants.get(t.id) is Variant.FORCED,
            sdh=variants.get(t.id) is Variant.SDH,
            quebec=lang == "fr" and is_quebec(t),
            ad=t.type == "audio" and is_audio_description(t),
            commentary=t.type == "audio" and bool(t.props.get("flag_commentary") or COMMENTARY_NAME_RE.search(t.name)),
        ))
    return result


def resolve(profile: tuple[Slot, ...], vo: str, native: str) -> list[tuple[Slot, str]]:
    """Slots with VO replaced by its language; a slot that appears twice (French VO) only once.

    A film in your native language doesn't need its full subtitles: only the forced ones
    (foreign lines, signs) are wanted then.
    """
    seen, slots = set(), []
    for slot in profile:
        lang = vo if slot.lang == VO else slot.lang
        if slot.kind == "subtitles" and not slot.forced and lang == vo == native:
            continue
        if (slot.kind, lang, slot.forced) not in seen:
            seen.add((slot.kind, lang, slot.forced))
            slots.append((slot, lang))
    return slots


# --- Targets -------------------------------------------------------------------------------------

def track_name(c: Candidate) -> str:
    """'Anglais', 'Anglais (SDH)', 'Français (forcés)', 'Français (VFQ)', 'Français (AD)'..."""
    tags = [tag for tag, on in (("SDH", c.sdh), ("forcés", c.forced), ("VFQ", c.quebec),
                                ("AD", c.ad), ("commentaire", c.commentary)) if on]
    label = language_label(c.lang)
    return f"{label} ({', '.join(tags)})" if tags else label


def language_props(lang: str, quebec: bool = False) -> dict[str, str]:
    known = find_language(lang)
    if not known:
        return {}                            # a language mkvpropre has no table entry for: left as is
    return {"language": known.iso639_2, "language-ietf": "fr-CA" if quebec else known.code}


def target(c: Candidate, cfg: Config, default: bool) -> dict[str, str]:
    t = {"name": track_name(c)} | language_props(c.lang, c.quebec) | {
        "flag-default": str(int(default)),
        "flag-forced": str(int(c.forced)),
        "flag-original": str(int(c.lang == cfg.original)),
    }
    if c.kind == "audio":
        t |= {"flag-commentary": str(int(c.commentary)), "flag-visual-impaired": str(int(c.ad))}
    else:
        t |= {"flag-hearing-impaired": str(int(c.sdh))}
    return t


# --- The plan ------------------------------------------------------------------------------------

def make_plan(media: MediaFile, cfg: Config, title: str | None) -> Plan:
    notes: list[str] = []
    warnings: list[str] = []
    videos = [t for t in media.tracks if t.type == "video"]
    others = [t for t in media.tracks if t.type not in ("video", "audio", "subtitles")]
    pool = candidates(media, cfg, notes)

    # Fill each slot of the profile with its best track
    chosen: list[tuple[Slot, str, Candidate]] = []
    taken: set[int] = set()
    for slot, lang in resolve(cfg.profile, cfg.original, cfg.native):
        best = min((c for c in pool if c.track.id not in taken and matches(c, slot, lang)), key=rank, default=None)
        if best:
            chosen.append((slot, lang, best))
            taken.add(best.track.id)
        elif not slot.forced:
            warnings.append(f"no {language_label(lang)} {slot.kind}" + (" (VO)" if lang == cfg.original else ""))
    rest = [c for c in pool if c.track.id not in taken]

    # Defaults: the first audio (the VO); subtitles in --default-subs, but only the forced
    # track when the default audio is already in that language (full ones would repeat it)
    audio = [c for _, _, c in chosen if c.kind == "audio"]
    default_audio = audio[0] if audio else None
    default_sub = None
    if cfg.default_subs:
        want_forced = default_audio is not None and default_audio.lang == cfg.default_subs
        default_sub = next((c for slot, lang, c in chosen if c.kind == "subtitles"
                            and lang == cfg.default_subs and slot.forced == want_forced), None)

    plans: list[TrackPlan] = []
    for i, t in enumerate(videos):
        video = {"flag-default": str(int(i == 0)), "flag-forced": "0"} | language_props(cfg.original)
        if title:
            video["name"] = title
        plans.append(TrackPlan(t, Kind.VIDEO, video))
    for _, _, c in chosen:
        plans.append(TrackPlan(c.track, Kind.AUDIO if c.kind == "audio" else Kind.SUBS,
                               target(c, cfg, default=c is default_audio or c is default_sub)))

    # The rest: renamed, at the end, never default; removed with --drop-other-tracks
    dropped: list[Track] = []
    if cfg.drop_other:
        keep_audio = not audio            # never leave a file without sound
        kept = [c for c in rest if keep_audio and c.kind == "audio"]
        dropped = [c.track for c in rest if c not in kept] + others
        if kept:
            warnings.append("kept, no wanted audio track: " + ", ".join(c.track.describe() for c in kept))
        rest, others = kept, []
    for c in rest:
        plans.append(TrackPlan(c.track, Kind.OTHER, target(c, cfg, default=False)))
    for t in others:
        plans.append(TrackPlan(t, Kind.OTHER, {"flag-default": "0"}))

    if dropped:
        warnings.append("removing: " + ", ".join(t.describe() for t in dropped))
    if rest or others:
        warnings.append("kept at the end: " + ", ".join(tp.track.describe() for tp in plans if tp.kind is Kind.OTHER))
    if len(videos) != 1:
        warnings.append(f"{len(videos)} video tracks found")
    if title is None:
        warnings.append("no episode title found, video track name and file title left as is")
    if any(a.is_font for a in media.attachments) and \
            any(t.codec in ("S_TEXT/ASS", "S_TEXT/SSA") for t in media.tracks):
        warnings.append("fonts will be removed while ASS/SSA subtitles are present: "
                        "their styling may fall back to default fonts")
    return Plan(media, tuple(plans), title, tuple(notes), tuple(warnings), tuple(dropped))
