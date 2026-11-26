"""Planning: pure logic, no MKVToolNix needed."""
from __future__ import annotations

from dataclasses import replace

import pytest

from mkvpropre.config import PROFILE, VO, Kind, Slot, Variant
from mkvpropre.model import Attachment, PROPERTY_KEYS
from mkvpropre.plan import (ContentVerdict, Plan, TrackPlan, content_verdicts, decide_variant, detect_lang,
                            is_audio_description, is_quebec, make_plan, metadata_variant, resolve)
from conftest import media, stats, track


def by_kind(plan: Plan, kind: Kind) -> list[TrackPlan]:
    return [tp for tp in plan.tracks if tp.kind is kind]


def sets(args: list[str]) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args) if a == "--set"]


def layout(plan: Plan) -> list[tuple]:
    """(track id, name, default) for every kept track, in target order."""
    return [(tp.track.id, tp.target.get("name"), tp.target["flag-default"]) for tp in plan.tracks]


# --- content verdicts ------------------------------------------------------------------

def test_forced_relative_to_fullest_track(cfg):
    full, forced = track(3, "subtitles"), track(4, "subtitles")
    m = media(full, forced, content={3: stats(366, 0.0), 4: stats(12, 0.0)})
    v = content_verdicts([full, forced], m, cfg)
    assert v[3].forced is False and v[4].forced is True
    assert "3% of fullest" in v[4].reason


def test_forced_by_rate_when_alone(cfg):
    t = track(3, "subtitles")
    m = media(t, content={3: stats(20, 0.0)})     # 20 events in 21 min < 2/min
    assert content_verdicts([t], m, cfg)[3].forced is True


def test_lone_normal_track_is_not_forced(cfg):
    t = track(3, "subtitles")
    m = media(t, content={3: stats(394, 0.0)})
    assert content_verdicts([t], m, cfg)[3].forced is False


def test_no_duration_only_relative_check(cfg):
    t = track(3, "subtitles")
    m = media(t, content={3: stats(5, 0.0)}, duration_ns=None)
    assert content_verdicts([t], m, cfg)[3].forced is False


def test_sdh_threshold(cfg):
    a, b = track(3, "subtitles"), track(4, "subtitles")
    m = media(a, b, content={3: stats(200, 0.019), 4: stats(220, 0.02)})
    v = content_verdicts([a, b], m, cfg)
    assert v[3].sdh is False and v[4].sdh is True


def test_light_sdh_track_is_sdh(cfg):
    # Real case: My Wife and Kids S01E02, English SDH with only a few "(sighs)", "♪ Whoo ♪"
    t = track(3, "subtitles")
    assert content_verdicts([t], media(t, content={3: stats(380, 0.034)}), cfg)[3].sdh is True


def test_thresholds_come_from_config(cfg):
    t = track(3, "subtitles")
    m = media(t, content={3: stats(200, 0.05)})
    assert content_verdicts([t], m, replace(cfg, sdh_min_ratio=0.06))[3].sdh is False


@pytest.mark.parametrize("forced, sdh, meta, expected, source", [
    (None, None, Variant.FORCED, Variant.FORCED, "flags/name"),      # no content data
    (True, False, Variant.FULL, Variant.FORCED, "content"),          # content beats flags
    (False, None, Variant.FORCED, Variant.FULL, "content for forced"),  # "FR Forced" with 190 events
    (False, None, Variant.SDH, Variant.SDH, "content for forced"),   # image subs: SDH from flags
    (False, True, Variant.FULL, Variant.SDH, "content"),
    (False, False, Variant.SDH, Variant.FULL, "content"),
])
def test_decide_variant(forced, sdh, meta, expected, source):
    variant, src = decide_variant(ContentVerdict(forced, sdh, ""), meta)
    assert variant is expected and src.startswith(source)


@pytest.mark.parametrize("props, expected", [
    ({}, Variant.FULL),
    ({"forced_track": True}, Variant.FORCED),
    ({"track_name": "FR Forced"}, Variant.FORCED),
    ({"track_name": "Français (forcés)"}, Variant.FORCED),
    ({"flag_hearing_impaired": True}, Variant.SDH),
    ({"track_name": "English SDH"}, Variant.SDH),
])
def test_metadata_variant(props, expected):
    name = props.pop("track_name", None)
    assert metadata_variant(track(3, "subtitles", name=name, **props)) is expected


# --- the profile ----------------------------------------------------------------------------------

def test_profile_is_vo_then_french():
    assert [(s.kind, s.lang, s.forced) for s in PROFILE] == [
        ("audio", VO, False), ("audio", "fr", False), ("subtitles", VO, False),
        ("subtitles", VO, True), ("subtitles", "fr", False), ("subtitles", "fr", True)]
    assert [s.default for s in PROFILE] == [True, True, False, False, True, True]
    assert [s.foreign_only for s in PROFILE] == [False, False, True, False, True, False]


def test_french_vo_fills_the_french_slots_once_without_full_subtitles():
    # French is the native language: a French film only wants its forced subtitles
    assert [(s.kind, lang, s.forced) for s, lang in resolve(PROFILE, "fr", "fr")] == [
        ("audio", "fr", False), ("subtitles", "fr", True)]


def test_foreign_vo_keeps_both_full_subtitles():
    assert [(s.kind, lang, s.forced) for s, lang in resolve(PROFILE, "en", "fr")] == [
        ("audio", "en", False), ("audio", "fr", False), ("subtitles", "en", False),
        ("subtitles", "en", True), ("subtitles", "fr", False), ("subtitles", "fr", True)]


def test_native_language_comes_from_config():
    # someone whose native language is English: an English film only wants English forced subtitles
    assert ("subtitles", "en", False) not in [(s.kind, lang, s.forced) for s, lang in resolve(PROFILE, "en", "en")]


@pytest.mark.parametrize("lang, ietf, name, expected", [
    ("eng", "en", None, "en"),
    ("fra", None, None, "fr"),
    ("fre", "fr-CA", None, "fr"),
    ("ger", "de", None, "de"),
    ("jpn", None, None, "ja"),
    ("und", None, "VFF", "fr"),           # name fallback when the tag says nothing
    ("und", None, "VOSTFR", "fr"),
    (None, None, "English SDH", "en"),
    ("und", None, None, "und"),
    ("kat", "ka", None, "ka"),            # no label for it, kept as is
])
def test_detect_lang(lang, ietf, name, expected):
    assert detect_lang(track(0, "audio", lang=lang, ietf=ietf, name=name)) == expected


# --- your file ------------------------------------------------------------------------------------

def test_user_file_targets(cfg, user_file):
    plan = make_plan(user_file, cfg, "Pilot")
    assert not plan.needs_remux
    video, en_audio, fr_audio, en_sub, fr_sub = plan.tracks
    assert video.target == {"flag-default": "1", "flag-forced": "0", "language": "eng",
                            "language-ietf": "en", "name": "Pilot"}
    assert en_audio.target == {"name": "Anglais", "language": "eng", "language-ietf": "en",
                               "flag-default": "1", "flag-forced": "0", "flag-original": "1",
                               "flag-commentary": "0", "flag-visual-impaired": "0"}
    assert fr_audio.target["name"] == "Français" and fr_audio.target["flag-default"] == "0"
    assert en_sub.target == {"name": "Anglais", "language": "eng", "language-ietf": "en", "flag-default": "0",
                             "flag-forced": "0", "flag-original": "1", "flag-hearing-impaired": "0"}
    assert fr_sub.target["flag-default"] == "1" and fr_sub.target["name"] == "Français"


def test_user_file_propedit_args_only_contain_changes(cfg, user_file):
    args = make_plan(user_file, cfg, "Pilot").propedit_args()
    assert args[:4] == ["--edit", "info", "--set", "title=Pilot"]
    s = sets(args)
    assert "language=eng" not in s and "flag-forced=0" not in s      # already right
    assert "name=Anglais" in s and "flag-original=1" in s


def test_normalized_file_has_nothing_to_do(cfg, user_file):
    plan = make_plan(user_file, cfg, "Pilot")
    done = replace(user_file, title="Pilot", tracks=tuple(
        replace(tp.track, props=tp.track.props | {PROPERTY_KEYS[k]: (v == "1" if k.startswith("flag-") else v)
                                                  for k, v in tp.target.items()})
        for tp in plan.tracks))
    assert make_plan(done, cfg, "Pilot").propedit_args() == []


# --- your rules: VO + French, plain subtitles preferred, forced kept, the rest at the end --------

def full_house():
    """Every kind of track, deliberately in a bad order."""
    return media(
        track(0, "subtitles", lang="eng", name="English SDH", flag_hearing_impaired=True),
        track(1, "audio", lang="fre", ietf="fr-CA", name="VFQ", audio_channels=6),
        track(2, "video"),
        track(3, "audio", lang="eng", name="English", audio_channels=6),
        track(4, "audio", lang="fre", name="VF AD", audio_channels=6),
        track(5, "audio", lang="fre", ietf="fr-FR", name="VFF", audio_channels=6),
        track(6, "audio", lang="ger", name="Deutsch", audio_channels=6),
        track(7, "audio", lang="eng", name="Director's commentary", audio_channels=2),
        track(8, "subtitles", lang="eng", name="English"),
        track(9, "subtitles", lang="eng", name="English Forced", forced_track=True),
        track(10, "subtitles", lang="fre", ietf="fr-CA", name="VFQ"),
        track(11, "subtitles", lang="fre", name="French SDH", flag_hearing_impaired=True),
        track(12, "subtitles", lang="fre", name="French"),
        track(13, "subtitles", lang="fre", name="French Forced", forced_track=True),
        track(14, "subtitles", lang="spa", name="Spanish"),
        content={0: stats(1500, 0.15), 8: stats(1300, 0.0), 9: stats(30, 0.0), 10: stats(1310, 0.0),
                 11: stats(1450, 0.12), 12: stats(1280, 0.0), 13: stats(35, 0.0), 14: stats(1250, 0.0)},
        duration_ns=120 * 60 * 10**9)


def test_wanted_tracks_then_the_rest_renamed(cfg):
    plan = make_plan(full_house(), cfg, "Film")
    assert layout(plan) == [
        (2, "Film", "1"),
        (3, "Anglais", "1"),                    # audio VO
        (5, "Français", "0"),                   # audio VFF
        (8, "Anglais", "0"),                    # subtitles VO, plain rather than SDH
        (9, "Anglais (forcés)", "0"),           # subtitles VO forced
        (12, "Français", "1"),                  # subtitles French, plain rather than SDH or VFQ
        (13, "Français (forcés)", "0"),         # subtitles French forced
        # the rest, in file order, renamed, never default
        (0, "Anglais (SDH)", "0"),
        (1, "Français (VFQ)", "0"),
        (4, "Français (AD)", "0"),
        (6, "Allemand", "0"),
        (7, "Anglais (commentaire)", "0"),
        (10, "Français (VFQ)", "0"),
        (11, "Français (SDH)", "0"),
        (14, "Espagnol", "0"),
    ]
    assert plan.dropped == () and plan.needs_remux
    assert [tp.kind for tp in plan.tracks][-8:] == [Kind.REST] * 8


def test_the_rest_gets_accurate_flags_and_languages(cfg):
    rest = {tp.track.id: tp.target for tp in by_kind(make_plan(full_house(), cfg, "Film"), Kind.REST)}
    assert rest[0]["flag-hearing-impaired"] == "1" and rest[0]["flag-original"] == "1"
    assert rest[1]["language-ietf"] == "fr-CA"
    assert rest[4]["flag-visual-impaired"] == "1"
    assert rest[6]["language"] == "ger" and rest[6]["flag-original"] == "0"
    assert rest[7]["flag-commentary"] == "1"
    assert rest[10]["language-ietf"] == "fr-CA"


def test_drop_other_tracks_removes_the_rest(cfg):
    plan = make_plan(full_house(), replace(cfg, drop_other=True), "Film")
    assert [t.id for t in plan.dropped] == [0, 1, 4, 6, 7, 10, 11, 14]
    assert plan.order == [2, 3, 5, 8, 9, 12, 13]
    assert any(w.startswith("removing: #0 subtitles eng 'English SDH'") for w in plan.warnings)


@pytest.mark.parametrize("drop", [False, True])
def test_plan_is_stable_after_the_remux(cfg, drop):
    c = replace(cfg, drop_other=drop)
    first = make_plan(full_house(), c, "Film")
    second = make_plan(first.media.reordered(first.order), c, "Film")
    assert second.dropped == () and not second.needs_remux
    assert [tp.target for tp in first.tracks] == [tp.target for tp in second.tracks]


def test_sdh_fills_the_slot_when_there_is_no_plain_track(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"), track(2, "audio", lang="fre"),
              track(3, "subtitles", lang="fre", name="French SDH", flag_hearing_impaired=True),
              content={3: stats(1500, 0.2)})
    [sub] = by_kind(make_plan(m, cfg, None), Kind.SUBS)
    assert (sub.target["name"], sub.target["flag-default"], sub.target["flag-hearing-impaired"]) == \
        ("Français (SDH)", "1", "1")


def test_vfq_fills_the_french_slot_when_there_is_no_vff(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"),
              track(2, "audio", lang="fre", ietf="fr-CA", name="VFQ"))
    [_, fr] = by_kind(make_plan(m, cfg, None), Kind.AUDIO)
    assert (fr.track.id, fr.target["name"], fr.target["language-ietf"]) == (2, "Français (VFQ)", "fr-CA")


def test_two_french_dubs_are_no_longer_ambiguous(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"),
              track(2, "audio", lang="fre", name="VF 2.0", audio_channels=2),
              track(3, "audio", lang="fre", name="VF 5.1", audio_channels=6))
    plan = make_plan(m, cfg, None)
    assert [tp.track.id for tp in by_kind(plan, Kind.AUDIO)] == [1, 3]      # the 5.1 one
    assert [tp.track.id for tp in by_kind(plan, Kind.REST)] == [2]


def test_commentary_is_never_the_main_audio_when_there_is_another(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng", name="Commentary", audio_channels=6),
              track(2, "audio", lang="eng", name="English", audio_channels=2))
    assert [tp.track.id for tp in by_kind(make_plan(m, cfg, None), Kind.AUDIO)] == [2]


def test_missing_tracks_are_reported(cfg):
    plan = make_plan(media(track(0, "video"), track(1, "audio", lang="eng")), cfg, None)
    assert "no Français audio" in plan.warnings
    assert "no Anglais subtitles (VO)" in plan.warnings and "no Français subtitles" in plan.warnings
    assert not any("forced" in w for w in plan.warnings)                   # forced tracks are optional


def test_only_first_video_is_default(cfg):
    plan = make_plan(media(track(0, "video"), track(1, "video")), cfg, None)
    assert [tp.target["flag-default"] for tp in plan.tracks] == ["1", "0"]
    assert "2 video tracks found" in plan.warnings


def test_no_title_leaves_names_alone(cfg, user_file):
    plan = make_plan(user_file, cfg, None)
    assert "name" not in plan.tracks[0].target
    assert any("no episode title" in w for w in plan.warnings)


# --- VO ---------------------------------------------------------------------------------------------

def french_film(forced: bool = True):
    tracks = [track(0, "video"), track(1, "audio", lang="eng"), track(2, "audio", lang="fre"),
              track(3, "subtitles", lang="eng"), track(4, "subtitles", lang="fre")]
    content = {3: stats(1450, 0.0), 4: stats(1500, 0.0)}
    if forced:
        tracks.append(track(5, "subtitles", lang="fre", name="Forced"))
        content[5] = stats(20, 0.0)
    return media(*tracks, content=content, duration_ns=110 * 60 * 10**9)


def test_french_vo_film(cfg):
    plan = make_plan(french_film(), cfg.with_original("fr"), "Amélie")
    assert layout(plan) == [
        (0, "Amélie", "1"),
        (2, "Français", "1"),                  # VO audio = French
        (5, "Français (forcés)", "1"),         # only the forced subtitles: French is the native language
        (1, "Anglais", "0"), (3, "Anglais", "0"), (4, "Français", "0"),   # the rest
    ]
    assert plan.tracks[0].target["language-ietf"] == "fr"
    assert plan.tracks[1].target["flag-original"] == "1"


def test_french_vo_film_with_drop_keeps_french_audio_and_forced_only(cfg):
    plan = make_plan(french_film(), replace(cfg, drop_other=True).with_original("fr"), "Amélie")
    assert plan.order == [0, 2, 5]
    assert [t.id for t in plan.dropped] == [1, 3, 4]


def test_french_vo_without_forced_track_has_no_subtitles(cfg):
    plan = make_plan(french_film(forced=False), replace(cfg, drop_other=True).with_original("fr"), None)
    assert plan.order == [0, 2] and by_kind(plan, Kind.SUBS) == []
    assert not any("subtitles" in w and w.startswith("no ") for w in plan.warnings)   # not missing: unwanted


def test_japanese_vo(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"), track(2, "audio", lang="fre"),
              track(3, "audio", lang="jpn"), track(4, "subtitles", lang="jpn"), track(5, "subtitles", lang="fre"),
              content={4: stats(1400, 0.0), 5: stats(1350, 0.0)})
    plan = make_plan(m, cfg.with_original("ja"), "Le Voyage de Chihiro")
    assert layout(plan) == [
        (0, "Le Voyage de Chihiro", "1"),
        (3, "Japonais", "1"), (2, "Français", "0"),
        (4, "Japonais", "0"), (5, "Français", "1"),
        (1, "Anglais", "0"),                    # English is the rest when it isn't the VO
    ]
    assert plan.tracks[0].target["language"] == "jpn"
    assert plan.tracks[1].target["flag-original"] == "1"


def test_vo_audio_missing_is_reported(cfg):
    plan = make_plan(media(track(0, "video"), track(1, "audio", lang="fre")), cfg.with_original("ja"), None)
    assert "no Japonais audio (VO)" in plan.warnings
    assert by_kind(plan, Kind.AUDIO)[0].target["flag-default"] == "1"    # French becomes the default


def test_defaults_come_from_the_profile(cfg, user_file):
    # English film: the first default audio slot (VO) and the first default subtitle slot (French full)
    plan = make_plan(user_file, cfg, None)
    assert [(tp.track.id, tp.target["flag-default"]) for tp in plan.tracks if tp.kind is not Kind.VIDEO] == [
        (1, "1"), (2, "0"), (3, "0"), (4, "1")]


def test_french_forced_is_default_when_there_are_no_full_french_subtitles(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"), track(2, "subtitles", lang="eng"),
              track(3, "subtitles", lang="fre", name="Forced", forced_track=True),
              content={2: stats(1300, 0.0), 3: stats(20, 0.0)}, duration_ns=100 * 60 * 10**9)
    assert {tp.track.id: tp.target["flag-default"] for tp in by_kind(make_plan(m, cfg, None), Kind.SUBS)} == \
        {2: "0", 3: "1"}


def test_a_profile_without_default_subtitles(cfg, user_file):
    profile = tuple(replace(s, default=False) if s.kind == "subtitles" else s for s in PROFILE)
    plan = make_plan(user_file, replace(cfg, profile=profile), None)
    assert [tp.target["flag-default"] for tp in by_kind(plan, Kind.SUBS)] == ["0", "0"]


def test_duplicate_slots_keep_the_default(cfg):
    # French film: "VO forced" (not a default slot) and "French forced" (a default slot) are the same
    [*_, (forced, lang)] = resolve(PROFILE, "fr", "fr")
    assert (forced.kind, lang, forced.forced, forced.default) == ("subtitles", "fr", True, True)


# --- --drop-other-tracks safety ---------------------------------------------------------------------

def test_audio_is_kept_when_no_wanted_audio_exists(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="und"), track(2, "subtitles", lang="spa"))
    plan = make_plan(m, replace(cfg, drop_other=True), None)
    assert [t.id for t in plan.dropped] == [2]
    assert any("kept, no wanted audio track" in w for w in plan.warnings)


def test_other_track_types_are_dropped_too(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"),
              track(2, "buttons", codec="S_HDMV/TEXTST"))
    assert [t.id for t in make_plan(m, replace(cfg, drop_other=True), None).dropped] == [2]


# --- the real release that started it ----------------------------------------------------------------

def social_reckoning():
    """The.Social.Reckoning.2026.MULTI.VF2.Ad.2160P.WEBRip...-Amen.mkv, as mkvmerge saw it."""
    return media(
        track(0, "video", lang="und", ietf="und", default_track=True),
        track(1, "audio", lang="fre", ietf="fr-FR", name="French", default_track=True, audio_channels=6),
        track(2, "audio", lang="fre", ietf="fr-CA", name="French CA", audio_channels=6),
        track(3, "audio", lang="fre", ietf="fr-FR", name="French AD", audio_channels=6),
        track(4, "audio", lang="eng", ietf="en", name="English", audio_channels=6),
        track(5, "subtitles", lang="fre", ietf="fr-FR", name="French Forced", default_track=True, forced_track=True),
        track(6, "subtitles", lang="fre", ietf="fr-FR", name="French Full"),
        track(7, "subtitles", lang="fre", ietf="fr-CA", name="French CA Full"),
        track(8, "subtitles", lang="fre", ietf="fr-CA", name="French CA SDH", flag_hearing_impaired=True),
        track(9, "subtitles", lang="eng", ietf="en", name="English Full"),
        track(10, "subtitles", lang="eng", ietf="en", name="English SDH", flag_hearing_impaired=True),
        content={5: stats(36, 0.0), 6: stats(1911, 0.0), 7: stats(1310, 0.0), 8: stats(1500, 0.12),
                 9: stats(2045, 0.0), 10: stats(2398, 0.15)},
        duration_ns=112 * 60 * 10**9)


def test_social_reckoning(cfg):
    plan = make_plan(social_reckoning(), cfg, "The Social Reckoning")
    assert layout(plan) == [
        (0, "The Social Reckoning", "1"),
        (4, "Anglais", "1"), (1, "Français", "0"),
        (9, "Anglais", "0"),
        (6, "Français", "1"), (5, "Français (forcés)", "0"),
        (2, "Français (VFQ)", "0"), (3, "Français (AD)", "0"), (7, "Français (VFQ)", "0"),
        (8, "Français (SDH, VFQ)", "0"), (10, "Anglais (SDH)", "0"),
    ]


def test_social_reckoning_with_drop(cfg):
    plan = make_plan(social_reckoning(), replace(cfg, drop_other=True), "The Social Reckoning")
    assert plan.order == [0, 4, 1, 9, 6, 5]
    assert [t.id for t in plan.dropped] == [2, 3, 7, 8, 10]

def test_file_title_compared_after_unicode_normalization(cfg, user_file):
    stored = replace(user_file, title="Père et fils")   # "Père et fils", decomposed
    assert "title=Père et fils" not in set_values(make_plan(stored, cfg, "Père et fils").propedit_args())


def set_values(args: list[str]) -> list[str]:
    return sets(args) + [a for a in args if a.startswith("title=")]


def test_name_compared_after_unicode_normalization(cfg):
    stored = "Français"                 # what mkvpropedit stores on macOS
    t = track(2, "audio", lang="fre", ietf="fr", name=stored)
    tp = TrackPlan(t, Kind.AUDIO, {"name": "Français"})
    assert tp.changes() == {}


# --- attachments and tags ------------------------------------------------------------------

def test_attachments_and_tags_are_removed(cfg, user_file):
    m = replace(user_file, has_tags=True, attachments=(
        Attachment(1, "font.ttf", "font/ttf"), Attachment(2, "cover.jpg", "image/jpeg")))
    args = make_plan(m, cfg, "Pilot").propedit_args()
    assert args[-6:] == ["--delete-attachment", "1", "--delete-attachment", "2", "--tags", "all:"]


def test_font_warning_only_with_ass(cfg, user_file):
    font = (Attachment(1, "Arial.TTF", "application/x-truetype-font"),)
    assert not any("fonts" in w for w in make_plan(replace(user_file, attachments=font), cfg, None).warnings)
    with_ass = replace(user_file, attachments=font, tracks=user_file.tracks + (
        track(5, "subtitles", lang="eng", codec="S_TEXT/ASS", name="Signs"),))
    with_ass = replace(with_ass, content=with_ass.content | {5: stats(6, 0.0)})
    assert any("fonts" in w for w in make_plan(with_ass, cfg, None).warnings)


# --- dry-run simulation of the remux ---------------------------------------------------------------

def test_reordered_simulates_mkvmerge(cfg):
    m = media(track(0, "subtitles", lang="fre"), track(1, "video", lang="und"),
              track(2, "audio", lang="eng"), track(3, "audio", lang="ger"),
              content={0: stats(300, 0.0)})
    r = m.reordered([1, 2, 0, 3])
    assert [(t.id, t.number, t.type) for t in r.tracks] == [
        (0, 1, "video"), (1, 2, "audio"), (2, 3, "subtitles"), (3, 4, "audio")]
    assert r.tracks[1].props["language_ietf"] == "en"      # filled in like mkvmerge does
    assert r.tracks[2].props["language_ietf"] == "fr"
    assert r.tracks[3].props["language_ietf"] == "de"
    assert r.content == {2: stats(300, 0.0)}
    assert not r.has_tags                                   # the remux writes no tags
    assert not make_plan(r, cfg, None).needs_remux

@pytest.mark.parametrize("props, name, expected", [
    ({"ietf": "fr-CA"}, "French", True),
    ({"ietf": "fr-FR"}, "French", False),
    ({"ietf": "fr-FR"}, "French CA", False),          # the tag wins when it has a region
    ({"ietf": "fr"}, "VFQ", True),                     # no region: the name decides
    ({"ietf": "fr"}, "Québécois", True),
    ({"ietf": "fr"}, "VFF", False),
    ({}, "Canadian French", True),
])
def test_is_quebec(props, name, expected):
    assert is_quebec(track(1, "audio", lang="fre", name=name, **props)) is expected


@pytest.mark.parametrize("name, flags, expected", [
    ("French AD", {}, True),
    ("Audio Description", {}, True),
    ("Audiodescription", {}, True),
    ("Français (malvoyants)", {}, True),
    ("French", {"flag_visual_impaired": True}, True),
    ("French", {}, False),
    ("Dolby ADvanced", {}, False),
    ("VF AD 5.1", {}, True),
])
def test_is_audio_description(name, flags, expected):
    assert is_audio_description(track(1, "audio", lang="fre", name=name, **flags)) is expected
