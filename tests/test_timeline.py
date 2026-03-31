import pytest

from sound_cut.config import build_profile
from sound_cut.models import AnalysisTrack, EditOperation, TimeRange
from sound_cut.timeline import build_edit_decision_list, kept_ranges, source_to_output_time


def test_build_edit_decision_list_keeps_short_pause_and_drops_long_pause() -> None:
    profile = build_profile("balanced")
    speech_ranges = (
        TimeRange(0.50, 1.00),
        TimeRange(1.18, 1.50),
        TimeRange(2.60, 3.20),
    )

    edl = build_edit_decision_list(
        duration_s=4.00,
        speech_ranges=speech_ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )

    kept = kept_ranges(edl)
    assert len(kept) == 2
    assert kept[0].start_s == pytest.approx(0.00)
    assert kept[0].end_s == pytest.approx(1.60)
    assert kept[1].start_s == pytest.approx(2.50)
    assert kept[1].end_s == pytest.approx(3.30)


def test_build_edit_decision_list_emits_discard_operations_for_removed_gaps() -> None:
    edl = build_edit_decision_list(
        duration_s=4.00,
        speech_ranges=(
            TimeRange(0.10, 1.00),
            TimeRange(2.50, 3.80),
        ),
        padding_ms=100,
        min_silence_ms=300,
        merge_gap_ms=0,
    )

    assert edl.operations == (
        EditOperation("keep", TimeRange(0.00, 1.10), "speech"),
        EditOperation("discard", TimeRange(1.10, 2.40), "silence"),
        EditOperation("keep", TimeRange(2.40, 4.00), "speech"),
    )
    assert kept_ranges(edl) == (
        TimeRange(0.00, 1.10),
        TimeRange(2.40, 4.00),
    )


def test_build_edit_decision_list_preserves_sub_threshold_edge_silence() -> None:
    edl = build_edit_decision_list(
        duration_s=2.00,
        speech_ranges=(TimeRange(0.20, 1.80),),
        padding_ms=0,
        min_silence_ms=300,
        merge_gap_ms=0,
    )

    assert edl.operations == (
        EditOperation("keep", TimeRange(0.00, 2.00), "speech"),
    )
    assert kept_ranges(edl) == (TimeRange(0.00, 2.00),)


def test_source_to_output_time_remaps_kept_ranges() -> None:
    profile = build_profile("balanced")
    speech_ranges = (
        TimeRange(0.50, 1.00),
        TimeRange(2.50, 3.00),
    )

    edl = build_edit_decision_list(
        duration_s=4.00,
        speech_ranges=speech_ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )

    assert source_to_output_time(edl, 0.60) == 0.60
    assert source_to_output_time(edl, 2.60) == 1.30
    assert source_to_output_time(edl, 1.70) is None


def test_min_silence_ms_changes_whether_nearby_speech_is_merged() -> None:
    speech_ranges = (
        TimeRange(0.50, 1.00),
        TimeRange(1.25, 1.75),
    )

    merged_edl = build_edit_decision_list(
        duration_s=2.00,
        speech_ranges=speech_ranges,
        padding_ms=0,
        min_silence_ms=300,
        merge_gap_ms=0,
    )

    split_edl = build_edit_decision_list(
        duration_s=2.00,
        speech_ranges=speech_ranges,
        padding_ms=0,
        min_silence_ms=200,
        merge_gap_ms=0,
    )

    assert kept_ranges(merged_edl) == (TimeRange(0.50, 2.00),)
    assert kept_ranges(split_edl) == (
        TimeRange(0.50, 1.00),
        TimeRange(1.25, 1.75),
    )


def test_analysis_track_metadata_is_immutable_and_copied() -> None:
    metadata = {"speaker": "alice"}
    track = AnalysisTrack(
        name="vad",
        ranges=(TimeRange(0.00, 1.00),),
        metadata=metadata,
    )

    metadata["speaker"] = "bob"

    assert track.metadata["speaker"] == "alice"

    with pytest.raises(TypeError):
        track.metadata["speaker"] = "carol"


def test_build_edit_decision_list_preserves_full_precision_boundaries() -> None:
    edl = build_edit_decision_list(
        duration_s=2.0,
        speech_ranges=(TimeRange(0.1234, 1.2345),),
        padding_ms=1,
        min_silence_ms=0,
        merge_gap_ms=0,
    )

    keep_range = kept_ranges(edl)[0]
    assert keep_range.start_s == pytest.approx(0.1224)
    assert keep_range.end_s == pytest.approx(1.2355)
