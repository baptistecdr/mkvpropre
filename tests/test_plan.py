"""Planning: pure logic, no MKVToolNix needed."""
from __future__ import annotations

from dataclasses import replace

import pytest

from mkvpropre.config import Kind, Variant
from mkvpropre.model import Attachment, PROPERTY_KEYS
from mkvpropre.plan import (ContentVerdict, Plan, PlanError, TrackPlan, content_verdicts,
                                decide_variant, is_audio_description, is_quebec, language_order, make_plan,
                                metadata_variant)
from conftest import media, stats, track


def by_kind(plan: Plan, kind: Kind) -> list[TrackPlan]:
    return [tp for tp in plan.tracks if tp.kind is kind]


def sets(args: list[str]) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args) if a == "--set"]


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


# --- make_plan: the user's file ------------------------------------------------------------

def test_user_file_targets(cfg, user_file):
    plan = make_plan(user_file, cfg, "Pilot")
    assert not plan.needs_remux
    video, en_audio, fr_audio, en_sub, fr_sub = plan.tracks
    assert video.target == {"flag-default": "1", "flag-forced": "0", "language": "eng",
                            "language-ietf": "en", "name": "Pilot"}
    assert en_audio.target == {"name": "Anglais", "language": "eng", "language-ietf": "en",
                               "flag-original": "1", "flag-default": "1", "flag-forced": "0",
                               "flag-commentary": "0", "flag-visual-impaired": "0"}
    assert fr_audio.target["name"] == "Français" and fr_audio.target["flag-default"] == "0"
    assert fr_audio.target["flag-original"] == "0"
    assert en_sub.target | {} == {"name": "Anglais", "language": "eng", "language-ietf": "en",
                                  "flag-original": "1", "flag-default": "0", "flag-forced": "0",
                                  "flag-hearing-impaired": "0"}
    assert fr_sub.target["flag-default"] == "1" and fr_sub.target["name"] == "Français"


def test_user_file_propedit_args_only_contain_changes(cfg, user_file):
    args = make_plan(user_file, cfg, "Pilot").propedit_args()
    assert args[:4] == ["--edit", "info", "--set", "title=Pilot"]
    assert "--edit" in args and "track:@2" in args
    s = sets(args)
    assert "language=eng" not in s            # already right on every track
    assert "flag-forced=0" not in s           # already unset
    assert "name=Anglais" in s and "flag-original=1" in s
    assert "--tags" not in args and "--delete-attachment" not in args


def test_normalized_file_has_nothing_to_do(cfg, user_file):
    plan = make_plan(user_file, cfg, "Pilot")
    done = replace(user_file, title="Pilot", tracks=tuple(
        replace(tp.track, props=tp.track.props | {PROPERTY_KEYS[k]: (v == "1" if k.startswith("flag-") else v)
                                                  for k, v in tp.target.items()})
        for tp in plan.tracks))
    assert make_plan(done, cfg, "Pilot").propedit_args() == []


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


# --- make_plan: ordering and defaults ------------------------------------------------------

def test_reorder_to_target_layout(cfg):
    m = media(
        track(0, "subtitles", lang="fre"), track(1, "audio", lang="fre"),
        track(2, "video"), track(3, "audio", lang="eng"), track(4, "subtitles", lang="eng"),
        track(5, "audio", lang="ger"),
        content={0: stats(300, 0.0), 4: stats(310, 0.0)})
    plan = make_plan(m, cfg, None)
    assert plan.needs_remux
    assert plan.order == [2, 3, 1, 4, 0, 5]
    assert plan.tracks[-1].kind is Kind.OTHER and plan.tracks[-1].target == {"flag-default": "0"}
    assert any("other tracks kept at the end" in w for w in plan.warnings)


def test_subtitle_variants_order_and_names(cfg):
    m = media(
        track(0, "video"), track(1, "audio", lang="eng"), track(2, "audio", lang="fre"),
        track(3, "subtitles", lang="fre", name="FR"),            # actually forced
        track(4, "subtitles", lang="fre", name="FR Forced"),     # actually full
        track(5, "subtitles", lang="eng", name="Track 5"),       # actually SDH
        track(6, "subtitles", lang="eng", name="Track 6"),
        content={3: stats(6, 0.0), 4: stats(190, 0.0), 5: stats(230, 0.17), 6: stats(200, 0.0)})
    plan = make_plan(m, cfg, None)
    subs = [(tp.track.id, tp.target["name"], tp.target["flag-default"], tp.target["flag-forced"],
             tp.target["flag-hearing-impaired"]) for tp in by_kind(plan, Kind.SUBS)]
    assert subs == [
        (6, "Anglais", "0", "0", "0"),
        (5, "Anglais (SDH)", "0", "0", "1"),
        (4, "Français", "1", "0", "0"),
        (3, "Français (forcés)", "0", "1", "0"),
    ]
    assert any("flags/name said forced" in n for n in plan.notes)


def test_sdh_is_default_when_no_plain_french_track(cfg):
    m = media(track(0, "video"), track(1, "subtitles", lang="fre"), track(2, "subtitles", lang="fre"),
              content={1: stats(250, 0.2), 2: stats(5, 0.0)})
    [sdh, forced] = by_kind(make_plan(m, cfg, None), Kind.SUBS)
    assert sdh.target["name"] == "Français (SDH)" and sdh.target["flag-default"] == "1"
    assert forced.target["flag-default"] == "0"


def test_first_audio_is_default_without_english(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="fre"))
    [fr] = by_kind(make_plan(m, cfg, None), Kind.AUDIO)
    assert fr.target["flag-default"] == "1"


def test_commentary_is_not_main_audio(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"),
              track(2, "audio", lang="eng", name="Director's commentary"))
    plan = make_plan(m, cfg, None)
    assert [tp.track.id for tp in by_kind(plan, Kind.AUDIO)] == [1]
    assert [tp.track.id for tp in by_kind(plan, Kind.OTHER)] == [2]


def test_only_first_video_is_default(cfg):
    m = media(track(0, "video"), track(1, "video"))
    plan = make_plan(m, cfg, None)
    assert [tp.target["flag-default"] for tp in plan.tracks] == ["1", "0"]
    assert "2 video tracks found" in plan.warnings


def test_no_title_leaves_names_alone(cfg, user_file):
    plan = make_plan(user_file, cfg, None)
    assert "name" not in plan.tracks[0].target
    assert "--edit" not in plan.propedit_args()[:2] or plan.propedit_args()[1] != "info"
    assert any("no episode title" in w for w in plan.warnings)


def test_vo_language_from_config(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="fre"))
    plan = make_plan(m, replace(cfg, original="fr"), None)
    assert plan.tracks[0].target["language-ietf"] == "fr"
    assert plan.tracks[1].target["flag-original"] == "1"


def french_film(cfg, *, forced: bool):
    tracks = [track(0, "video"), track(1, "audio", lang="fre"), track(2, "audio", lang="eng"),
              track(3, "subtitles", lang="fre"), track(4, "subtitles", lang="eng")]
    content = {3: stats(1500, 0.0), 4: stats(1450, 0.0)}
    if forced:
        tracks.append(track(5, "subtitles", lang="fre"))
        content[5] = stats(20, 0.0)
    return make_plan(media(*tracks, content=content, duration_ns=110 * 60 * 10**9), cfg.with_original("fr"), "Amélie")


def defaults_of(plan, kind):
    return {(tp.target.get("language-ietf"), tp.target["name"]): tp.target["flag-default"]
            for tp in by_kind(plan, kind)}


def test_french_vo_film(cfg):
    plan = french_film(cfg, forced=True)
    assert plan.tracks[0].target["language-ietf"] == "fr"                    # video = VO
    assert defaults_of(plan, Kind.AUDIO) == {("fr", "Français"): "1", ("en", "Anglais"): "0"}
    assert {tp.target["language-ietf"]: tp.target["flag-original"]
            for tp in by_kind(plan, Kind.AUDIO)} == {"en": "0", "fr": "1"}
    # French audio: the full French subtitles are not default, the French forced ones are
    assert defaults_of(plan, Kind.SUBS) == {("en", "Anglais"): "0", ("fr", "Français"): "0",
                                            ("fr", "Français (forcés)"): "1"}


def test_vo_comes_first(cfg):
    plan = french_film(cfg, forced=True)
    layout = [(tp.kind.value, tp.target.get("language-ietf"), tp.target.get("name")) for tp in plan.tracks]
    assert layout == [
        ("video", "fr", "Amélie"),
        ("audio", "fr", "Français"), ("audio", "en", "Anglais"),
        ("subtitles", "fr", "Français"), ("subtitles", "fr", "Français (forcés)"),
        ("subtitles", "en", "Anglais"),
    ]
    assert plan.needs_remux        # the French forced track moves before the English subtitles


def test_english_vo_keeps_english_first(cfg, user_file):
    plan = make_plan(user_file, cfg.with_original("en"), "Pilot")
    assert [tp.target.get("language-ietf") for tp in plan.tracks] == ["en", "en", "fr", "en", "fr"]


@pytest.mark.parametrize("vo, expected", [("en", ["en", "fr"]), ("fr", ["fr", "en"]), ("ja", ["en", "fr"])])
def test_language_order(cfg, vo, expected):
    assert language_order(cfg.with_original(vo)) == expected


def test_french_vo_film_without_forced_track_has_no_default_subs(cfg):
    plan = french_film(cfg, forced=False)
    assert set(defaults_of(plan, Kind.SUBS).values()) == {"0"}


def test_default_subs_none(cfg, user_file):
    plan = make_plan(user_file, replace(cfg, default_subs=None), "Pilot")
    assert set(defaults_of(plan, Kind.SUBS).values()) == {"0"}


def test_default_subs_english_under_french_audio(cfg):
    plan = french_film(replace(cfg, default_subs="en"), forced=True)
    assert defaults_of(plan, Kind.SUBS) == {("en", "Anglais"): "1", ("fr", "Français"): "0",
                                            ("fr", "Français (forcés)"): "0"}


def test_default_subs_same_as_audio_language_is_not_full(cfg, user_file):
    # English audio + --default-subs en: full English subtitles would repeat the dialogue
    plan = make_plan(user_file, replace(cfg, default_subs="en"), "Pilot")
    assert set(defaults_of(plan, Kind.SUBS).values()) == {"0"}


def test_unsupported_vo(cfg):
    m = media(track(0, "video", lang="jpn"), track(1, "audio", lang="jpn"), track(2, "audio", lang="eng"),
              track(3, "audio", lang="fre"))
    plan = make_plan(m, cfg.with_original("ja"), "Le Voyage de Chihiro")
    assert "language" not in plan.tracks[0].target                          # video language left as is
    assert [tp.target["flag-original"] for tp in by_kind(plan, Kind.AUDIO)] == ["0", "0"]
    assert defaults_of(plan, Kind.AUDIO) == {("en", "Anglais"): "1", ("fr", "Français"): "0"}
    assert [tp.track.id for tp in by_kind(plan, Kind.OTHER)] == [1]        # Japanese audio kept at the end
    assert any("VO is 'ja'" in w for w in plan.warnings)


def test_with_original(cfg):
    assert (cfg.with_original("fr").original, cfg.with_original("fr").default_audio) == ("fr", "fr")
    assert (cfg.with_original("ja").original, cfg.with_original("ja").default_audio) == ("ja", "en")


# --- make_plan: ambiguity ------------------------------------------------------------------

def test_two_main_audio_tracks_same_language_is_an_error(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="fre", ietf="fr-FR", name="VF 5.1"),
              track(2, "audio", lang="fre", ietf="fr-FR", name="VF 2.0"))
    with pytest.raises(PlanError, match="2 'fr' audio tracks"):
        make_plan(m, cfg, None)


def test_two_full_subtitle_tracks_same_language_is_an_error(cfg):
    m = media(track(0, "video"), track(1, "subtitles", lang="eng"), track(2, "subtitles", lang="eng"),
              content={1: stats(300, 0.0), 2: stats(310, 0.0)})
    with pytest.raises(PlanError, match="2 'en' full subtitle tracks"):
        make_plan(m, cfg, None)


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


# --- dry-run simulation of the remux ---------------------------------------------------------

def test_reordered_simulates_mkvmerge(cfg):
    m = media(track(0, "subtitles", lang="fre"), track(1, "video", lang="und"),
              track(2, "audio", lang="eng"), track(3, "audio", lang="ger"),
              content={0: stats(300, 0.0)})
    r = m.reordered([1, 2, 0, 3])
    assert [(t.id, t.number, t.type) for t in r.tracks] == [
        (0, 1, "video"), (1, 2, "audio"), (2, 3, "subtitles"), (3, 4, "audio")]
    assert r.tracks[1].props["language_ietf"] == "en"      # filled in like mkvmerge does
    assert r.tracks[2].props["language_ietf"] == "fr"
    assert "language_ietf" not in r.tracks[0].props or r.tracks[0].props["language_ietf"] is None
    assert r.content == {2: stats(300, 0.0)}
    assert not r.has_tags                                   # the remux writes no tags
    assert not make_plan(r, cfg, None).needs_remux


def test_plan_after_reorder_keeps_decisions(cfg):
    m = media(track(0, "subtitles", lang="fre", name="FR"), track(1, "subtitles", lang="fre", name="FR Forced"),
              track(2, "video"), track(3, "audio", lang="eng"),
              content={0: stats(6, 0.0), 1: stats(190, 0.0)})
    first = make_plan(m, cfg, None)
    second = make_plan(m.reordered(first.order), cfg, None)
    assert [tp.target for tp in first.tracks] == [tp.target for tp in second.tracks]


# --- --drop-other-tracks ---------------------------------------------------------------------------

def mixed_file():
    return media(track(0, "video"), track(1, "audio", lang="eng"), track(2, "audio", lang="fre"),
                 track(3, "audio", lang="ger", name="DE"),
                 track(4, "audio", lang="eng", name="Director's commentary"),
                 track(5, "subtitles", lang="eng"), track(6, "subtitles", lang="spa", name="ES"),
                 track(7, "subtitles", lang="und"),
                 content={5: stats(400, 0.0)})


def test_other_tracks_are_kept_by_default(cfg):
    plan = make_plan(mixed_file(), cfg, None)
    assert plan.dropped == () and [tp.track.id for tp in by_kind(plan, Kind.OTHER)] == [3, 4, 6, 7]


def test_drop_other_tracks(cfg):
    plan = make_plan(mixed_file(), replace(cfg, drop_other=True), None)
    assert [t.id for t in plan.dropped] == [3, 4, 6, 7]
    assert plan.order == [0, 1, 2, 5] and plan.needs_remux
    assert by_kind(plan, Kind.OTHER) == []
    assert any(w.startswith("removing other tracks: #3 audio ger 'DE'") for w in plan.warnings)


def test_dropping_alone_needs_a_remux(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"), track(2, "subtitles", lang="spa"))
    plan = make_plan(m, replace(cfg, drop_other=True), None)
    assert plan.order == [0, 1] and plan.needs_remux


def test_vo_audio_is_never_dropped(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="jpn", ietf="ja"), track(2, "audio", lang="eng"),
              track(3, "audio", lang="ger", ietf="de"), track(4, "subtitles", lang="jpn", ietf="ja"))
    plan = make_plan(m, replace(cfg, drop_other=True).with_original("ja"), None)
    assert [t.id for t in plan.dropped] == [3, 4]                 # Japanese subtitles go, Japanese audio stays
    assert [tp.track.id for tp in by_kind(plan, Kind.OTHER)] == [1]
    assert any("it is the VO" in w for w in plan.warnings)


def test_audio_is_kept_when_there_is_no_main_audio(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="und"), track(2, "subtitles", lang="spa"))
    plan = make_plan(m, replace(cfg, drop_other=True), None)
    assert [t.id for t in plan.dropped] == [2]
    assert any("could leave no sound" in w for w in plan.warnings)


def test_after_dropping_the_plan_is_stable(cfg):
    drop_cfg = replace(cfg, drop_other=True)
    first = make_plan(mixed_file(), drop_cfg, None)
    second = make_plan(first.media.reordered(first.order), drop_cfg, None)
    assert second.dropped == () and not second.needs_remux



# --- Québec French and audio description ---------------------------------------------------------

def social_reckoning():
    """Real track list of The.Social.Reckoning.2026.MULTI.VF2.Ad.2160P.WEBRip...-Amen.mkv"""
    return media(
        track(0, "video", lang="und", ietf="und", default_track=True),
        track(1, "audio", lang="fre", ietf="fr-FR", name="French", default_track=True),
        track(2, "audio", lang="fre", ietf="fr-CA", name="French CA"),
        track(3, "audio", lang="fre", ietf="fr-FR", name="French AD"),
        track(4, "audio", lang="eng", ietf="en", name="English"),
        track(5, "subtitles", lang="fre", ietf="fr-FR", name="French Forced", default_track=True, forced_track=True),
        track(6, "subtitles", lang="fre", ietf="fr-FR", name="French Full"),
        track(7, "subtitles", lang="fre", ietf="fr-CA", name="French CA Full"),
        track(8, "subtitles", lang="fre", ietf="fr-CA", name="French CA SDH", flag_hearing_impaired=True),
        track(9, "subtitles", lang="eng", ietf="en", name="English Full"),
        track(10, "subtitles", lang="eng", ietf="en", name="English SDH", flag_hearing_impaired=True),
        content={5: stats(40, 0.0), 6: stats(1300, 0.0), 7: stats(1310, 0.0), 8: stats(1500, 0.12),
                 9: stats(1290, 0.0), 10: stats(1480, 0.15)},
        duration_ns=120 * 60 * 10**9)


def test_vfq_and_audio_description_are_kept_at_the_end_by_default(cfg):
    plan = make_plan(social_reckoning(), cfg, "The Social Reckoning")
    assert plan.dropped == ()
    layout = [(tp.track.id, tp.kind, tp.target.get("name"), tp.target["flag-default"]) for tp in plan.tracks]
    assert layout == [
        (0, Kind.VIDEO, "The Social Reckoning", "1"),
        (4, Kind.AUDIO, "Anglais", "1"), (1, Kind.AUDIO, "Français", "0"),      # VO first
        (9, Kind.SUBS, "Anglais", "0"), (10, Kind.SUBS, "Anglais (SDH)", "0"),
        (6, Kind.SUBS, "Français", "1"), (5, Kind.SUBS, "Français (forcés)", "0"),
        (2, Kind.OTHER, None, "0"), (3, Kind.OTHER, None, "0"),                # VFQ, AD: untouched, never default
        (7, Kind.OTHER, None, "0"), (8, Kind.OTHER, None, "0"),
    ]
    assert any("other tracks kept at the end: #2 audio fre 'French CA' (Québec French (VFQ)), "
               "#3 audio fre 'French AD' (audio description)" in w for w in plan.warnings)


def test_vfq_and_audio_description_are_removed_with_drop_other(cfg):
    plan = make_plan(social_reckoning(), replace(cfg, drop_other=True), "x")
    assert [t.id for t in plan.dropped] == [2, 3, 7, 8]
    assert [tp.track.id for tp in plan.tracks] == [0, 4, 1, 9, 10, 6, 5]
    assert any("removing other tracks: #2 audio fre 'French CA' (Québec French (VFQ))" in w for w in plan.warnings)


@pytest.mark.parametrize("drop", [False, True])
def test_plan_is_stable_after_handling_variants(cfg, drop):
    c = replace(cfg, drop_other=drop)
    first = make_plan(social_reckoning(), c, "x")
    second = make_plan(first.media.reordered(first.order), c, "x")
    assert second.dropped == () and not second.needs_remux
    assert [tp.target for tp in first.tracks] == [tp.target for tp in second.tracks]


def test_french_film_vfq_is_removed_despite_being_french(cfg):
    # VO French: the VFQ is French too, but the VO is the main French track, so it isn't protected
    m = media(track(0, "video"), track(1, "audio", lang="fre", ietf="fr-FR", name="VFF"),
              track(2, "audio", lang="fre", ietf="fr-CA", name="VFQ"), track(3, "audio", lang="eng"))
    plan = make_plan(m, replace(cfg, drop_other=True).with_original("fr"), "Amélie")
    assert [t.id for t in plan.dropped] == [2]
    assert not any("it is the VO" in w for w in plan.warnings)


def test_vfq_only_movie_keeps_its_french(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"),
              track(2, "audio", lang="fre", ietf="fr-CA", name="VFQ"),
              track(3, "subtitles", lang="fre", ietf="fr-CA", name="French CA"),
              content={3: stats(1300, 0.0)})
    plan = make_plan(m, cfg, None)
    assert plan.dropped == ()
    assert [tp.target["name"] for tp in by_kind(plan, Kind.AUDIO)] == ["Anglais", "Français"]


def test_audio_description_alone_is_kept(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng"),
              track(2, "audio", lang="fre", name="French AD"))
    assert make_plan(m, cfg, None).dropped == ()


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


def test_english_ca_is_not_treated_as_quebec(cfg):
    m = media(track(0, "video"), track(1, "audio", lang="eng", ietf="en-CA", name="English CA"),
              track(2, "audio", lang="fre"))
    assert make_plan(m, cfg, None).dropped == ()
