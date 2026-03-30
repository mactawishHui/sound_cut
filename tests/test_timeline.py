from sound_cut.config import build_profile
from sound_cut.models import TimeRange
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

    assert kept_ranges(edl) == (
        TimeRange(0.40, 1.60),
        TimeRange(2.50, 3.30),
    )


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

    assert source_to_output_time(edl, 0.60) == 0.20
    assert source_to_output_time(edl, 2.60) == 0.90
    assert source_to_output_time(edl, 1.70) is None
