"""What a Matroska file contains, as read from `mkvmerge -J`."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .config import LANGS

# mkvpropedit property name -> key in `mkvmerge -J` track properties
PROPERTY_KEYS = {
    "name": "track_name",
    "language": "language",
    "language-ietf": "language_ietf",
    "flag-default": "default_track",
    "flag-forced": "forced_track",
    "flag-original": "flag_original",
    "flag-commentary": "flag_commentary",
    "flag-hearing-impaired": "flag_hearing_impaired",
    "flag-visual-impaired": "flag_visual_impaired",
}


@dataclass(frozen=True)
class Track:
    id: int          # mkvmerge track ID (0-based, file order)
    number: int      # Matroska track number, used by mkvpropedit selectors
    type: str        # "video" / "audio" / "subtitles"
    codec: str
    props: dict      # raw `mkvmerge -J` properties

    @classmethod
    def from_json(cls, t: dict) -> Track:
        p = t["properties"]
        return cls(t["id"], p["number"], t["type"], p.get("codec_id", ""), p)

    @property
    def name(self) -> str:
        return self.props.get("track_name") or ""

    def current(self, prop: str) -> str:
        """Current value of a property, in mkvpropedit's notation."""
        value = self.props.get(PROPERTY_KEYS[prop])
        if prop.startswith("flag-"):
            return str(int(bool(value)))   # absent flag == unset
        return value or ""

    def describe(self) -> str:
        return f"#{self.id} {self.type} {self.props.get('language')} {self.name!r}"


@dataclass(frozen=True)
class Attachment:
    id: int
    file_name: str
    content_type: str

    @property
    def is_font(self) -> bool:
        return "font" in self.content_type or \
            Path(self.file_name).suffix.lower() in (".ttf", ".otf", ".ttc")


@dataclass(frozen=True)
class ContentStats:
    events: int | None = None       # number of subtitle events
    sdh_ratio: float | None = None  # share of events that look like SDH (text subs only)


@dataclass(frozen=True)
class MediaFile:
    path: Path
    title: str
    duration_ns: int | None
    tracks: tuple[Track, ...]
    attachments: tuple[Attachment, ...]
    has_tags: bool
    content: dict[int, ContentStats] = field(default_factory=dict)  # by track id

    @property
    def minutes(self) -> float | None:
        return self.duration_ns / 60e9 if self.duration_ns else None

    def reordered(self, order: list[int]) -> MediaFile:
        """The file as `mkvmerge --track-order` will write it (used for --dry-run)."""
        by_id = {t.id: t for t in self.tracks}
        tracks = tuple(replace(by_id[old], id=new, number=new + 1, props=remuxed_props(by_id[old].props))
                       for new, old in enumerate(order))
        # The remux writes no tags at all (see apply.remux).
        return replace(self, tracks=tracks, has_tags=False,
                       content=remap_content(self.content, order))


def remuxed_props(props: dict) -> dict:
    """mkvmerge fills in a missing IETF language tag from the legacy one."""
    if props.get("language_ietf"):
        return props
    legacy = (props.get("language") or "und").lower()
    ietf = next((key for key, spec in LANGS.items() if legacy in spec.codes), None)
    return props | {"language_ietf": ietf} if ietf else props


def remap_content(content: dict[int, ContentStats], order: list[int]) -> dict[int, ContentStats]:
    """After a remux, new track id `new` is old track `order[new]`."""
    return {new: content[old] for new, old in enumerate(order) if old in content}
