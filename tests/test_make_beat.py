from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import make_beat


def test_build_beat_drum_pattern_counts_hits():
    spec = {
        "tempo": 120,
        "bars": 1,
        "instruments": [
            {
                "type": "drum",
                "kit": "trap",
                "pattern": {
                    "kick": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
                    "snare": [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
                },
            }
        ],
    }
    midi, metadata = make_beat.build_beat(spec)
    assert metadata["total_notes"] == 6
    assert metadata["instruments"] == 1
    assert len(midi.instruments) == 1
    assert midi.instruments[0].is_drum


def test_build_beat_chord_progression_parses_sharps_and_qualities():
    spec = {
        "tempo": 120,
        "bars": 4,
        "instruments": [
            {
                "type": "chord",
                "instrument": "warm_pad",
                "progression": [
                    {"root": "Cmaj7", "start": 0, "duration": 4},
                    {"root": "F#m7", "start": 4, "duration": 4},
                    {"root": "Bbdim", "start": 8, "duration": 4},
                ],
            }
        ],
    }
    midi, metadata = make_beat.build_beat(spec)
    # maj7 = 4 notes, m7 = 4 notes, dim = 3 notes
    assert metadata["total_notes"] == 11


def test_build_beat_swing_offsets_odd_steps():
    spec_no_swing = {
        "tempo": 120,
        "bars": 1,
        "swing": 0.0,
        "instruments": [{
            "type": "drum",
            "pattern": {"hihat": [1] * 16},
        }],
    }
    spec_swing = {**spec_no_swing, "swing": 0.5}

    midi_a, _ = make_beat.build_beat(spec_no_swing)
    midi_b, _ = make_beat.build_beat(spec_swing)

    starts_a = sorted(n.start for n in midi_a.instruments[0].notes)
    starts_b = sorted(n.start for n in midi_b.instruments[0].notes)

    # Even-index notes (0, 2, 4, ...) should be identical.
    for i in range(0, 16, 2):
        assert starts_a[i] == starts_b[i]
    # Odd-index notes should be later in the swung version.
    for i in range(1, 16, 2):
        assert starts_b[i] > starts_a[i]


def test_build_beat_melodic_notes_respect_duration_and_pitch():
    spec = {
        "tempo": 120,
        "bars": 2,
        "instruments": [{
            "type": "melodic",
            "instrument": "electric_bass",
            "notes": [
                {"pitch": 36, "start": 0, "duration": 0.5, "velocity": 90},
                {"pitch": 43, "start": 2, "duration": 1.0, "velocity": 80},
            ],
        }],
    }
    midi, metadata = make_beat.build_beat(spec)
    assert metadata["total_notes"] == 2
    pitches = sorted(n.pitch for n in midi.instruments[0].notes)
    assert pitches == [36, 43]


def test_expand_pattern_handles_step_list():
    assert make_beat.expand_pattern([1, 0, 1, 0]) == [0, 2]
