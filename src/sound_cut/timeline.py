from __future__ import annotations

from sound_cut.models import EditDecisionList, EditOperation, TimeRange


def _merge_ranges(ranges: tuple[TimeRange, ...], merge_gap_ms: int) -> tuple[TimeRange, ...]:
    if not ranges:
        return ()

    merge_gap_s = merge_gap_ms / 1000
    merged = [ranges[0]]
    for current in ranges[1:]:
        previous = merged[-1]
        if current.start_s - previous.end_s <= merge_gap_s:
            merged[-1] = TimeRange(previous.start_s, max(previous.end_s, current.end_s))
        else:
            merged.append(current)
    return tuple(merged)


def _pad_ranges(ranges: tuple[TimeRange, ...], duration_s: float, padding_ms: int) -> tuple[TimeRange, ...]:
    padding_s = padding_ms / 1000
    return tuple(
        TimeRange(
            start_s=max(0.0, item.start_s - padding_s),
            end_s=min(duration_s, item.end_s + padding_s),
        )
        for item in ranges
    )


def build_edit_decision_list(
    *,
    duration_s: float,
    speech_ranges: tuple[TimeRange, ...],
    padding_ms: int,
    min_silence_ms: int,
    merge_gap_ms: int,
) -> EditDecisionList:
    merged = _merge_ranges(tuple(sorted(speech_ranges)), merge_gap_ms)
    padded = _pad_ranges(merged, duration_s, padding_ms)
    padded = _merge_ranges(padded, min_silence_ms)
    keep_ops = tuple(EditOperation("keep", item, "speech") for item in padded if item.duration_s > 0)
    return EditDecisionList(operations=keep_ops)


def kept_ranges(edl: EditDecisionList) -> tuple[TimeRange, ...]:
    return tuple(operation.range for operation in edl.operations if operation.action == "keep")


def source_to_output_time(edl: EditDecisionList, source_time_s: float) -> float | None:
    cursor = 0.0
    for keep_range in kept_ranges(edl):
        if keep_range.start_s <= source_time_s <= keep_range.end_s:
            return round(cursor + (source_time_s - keep_range.start_s), 3)
        cursor += keep_range.duration_s
    return None
