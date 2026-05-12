"""
Vybra Beats — Beat Rendering Engine
An agent submits patterns as JSON, we generate MIDI + render audio.

Usage:
    python scripts/make_beat.py < input.json > output/
"""
import json, sys, os, io, random, uuid
from typing import Optional

try:
    import pretty_midi
except ImportError:
    os.system("uv pip install pretty_midi")
    import pretty_midi

# ── GM Drum Map ───────────────────────────────────────────
GM_DRUMS = {
    "kick":   36, "kick2":   35,
    "snare":  38, "snare2": 40,
    "hihat":  42, "hihat_o": 46, "hihat_p": 44,
    "clap":   39, "clave":  75,
    "tom_low": 41, "tom_mid": 45, "tom_high": 48,
    "ride":   51, "crash":  49, "splash": 55,
}

# ── GM Melodic Map ────────────────────────────────────────
GM_INSTRUMENTS = {
    "electric_bass":     33, "acoustic_bass":    32,
    "synth_bass":        38, "sub_bass":         39,
    "warm_pad":          89, "string_ensemble":   48,
    "analog_lead":       80, "synth_pluck":      83,
    "electric_piano":     4, "organ":            16,
    "glass_chord":       91, "atmospheric":      90,
    "brass_section":     61, "plucked_guitar":   25,
}


def expand_pattern(pattern: list[float | int], steps_per_bar: int = 16) -> list[float]:
    """Normalize pattern to a list of beat positions (0-indexed 16th notes)."""
    if isinstance(pattern, list) and all(isinstance(v, int) for v in pattern):
        return [i for i, v in enumerate(pattern) if v]
    if isinstance(pattern, list) and all(isinstance(v, float) for v in pattern):
        return pattern
    return [i for i, v in enumerate(pattern) if v]


def build_beat(spec: dict) -> tuple[pretty_midi.PrettyMIDI, dict]:
    """Take a beat spec JSON, return (midi_object, metadata)."""
    tempo = spec.get("tempo", 120)
    bars = spec.get("bars", 4)
    beats_per_bar = spec.get("timeSignature", [4, 4])[0]
    total_beats = bars * beats_per_bar
    step_duration = 60.0 / tempo / 4  # 16th note duration
    total_time = total_beats * 60.0 / tempo

    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    midi_instruments = []
    note_count = 0
    swing = spec.get("swing", 0.0)

    for inst_spec in spec.get("instruments", []):
        inst_type = inst_spec.get("type", "drum")

        if inst_type == "drum":
            kit = inst_spec.get("kit", "trap")
            velocity = inst_spec.get("velocity", 100)
            pattern = inst_spec.get("pattern", {})
            pm_inst = pretty_midi.Instrument(program=0, is_drum=True,
                name=f"drums_{kit}")

            for drum_name, drum_pitch in GM_DRUMS.items():
                if drum_name in pattern:
                    hits = expand_pattern(pattern[drum_name])
                    for step in hits:
                        time = step * step_duration
                        if swing and step % 2:
                            time += step_duration * swing * 0.5
                        vel = random.randint(max(30, velocity - 20), velocity)
                        note = pretty_midi.Note(
                            velocity=vel, pitch=drum_pitch,
                            start=time, end=time + step_duration * 0.8
                        )
                        pm_inst.notes.append(note)
                        note_count += 1
            midi_instruments.append(pm_inst)

        elif inst_type == "melodic":
            instrument_name = inst_spec.get("instrument", "electric_bass")
            program = GM_INSTRUMENTS.get(instrument_name, 33)
            pm_inst = pretty_midi.Instrument(program=program, name=instrument_name)

            for note_spec in inst_spec.get("notes", []):
                pitch = note_spec["pitch"]
                start = note_spec.get("start", 0)
                dur = note_spec.get("duration", 0.5)
                vel = note_spec.get("velocity", 80)
                time = start * step_duration * 4  # Convert beat index to seconds
                note = pretty_midi.Note(
                    velocity=vel, pitch=pitch,
                    start=time, end=min(time + dur, total_time)
                )
                pm_inst.notes.append(note)
                note_count += 1
            midi_instruments.append(pm_inst)

        elif inst_type == "chord":
            instrument_name = inst_spec.get("instrument", "warm_pad")
            program = GM_INSTRUMENTS.get(instrument_name, 89)
            pm_inst = pretty_midi.Instrument(program=program, name=instrument_name)

            chord_map = {
                "maj": [0, 4, 7], "min": [0, 3, 7],
                "7": [0, 4, 7, 10], "m7": [0, 3, 7, 10],
                "maj7": [0, 4, 7, 11], "dim": [0, 3, 6],
                "m7b5": [0, 3, 6, 10], "aug": [0, 4, 8],
                "sus4": [0, 5, 7], "sus2": [0, 2, 7],
            }
            note_to_midi = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3,
                "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
                "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}

            for chord_spec in inst_spec.get("progression", []):
                root_str = chord_spec["root"]
                # Parse root note
                root_note = root_str[0].upper()
                root_acc = root_str[1] if len(root_str) > 1 and root_str[1] in "#b" else ""
                root_midi = note_to_midi.get(root_note + root_acc, 0)

                # Parse chord quality
                quality_start = 1 + len(root_acc)
                quality = root_str[quality_start:] if quality_start < len(root_str) else "maj"
                intervals = chord_map.get(quality, [0, 4, 7])

                start_beat = chord_spec.get("start", 0)
                dur = chord_spec.get("duration", 4)
                vel = chord_spec.get("velocity", 70)
                time = start_beat * 60.0 / tempo
                end_time = min(time + dur * 60.0 / tempo, total_time)

                for interval in intervals:
                    pitch = root_midi + interval + 36  # Start at a comfortable octave
                    note = pretty_midi.Note(
                        velocity=vel, pitch=pitch,
                        start=time, end=end_time
                    )
                    pm_inst.notes.append(note)
                    note_count += 1
            midi_instruments.append(pm_inst)

    for inst in midi_instruments:
        midi.instruments.append(inst)

    metadata = {
        "tempo": tempo,
        "bars": bars,
        "beats_per_bar": beats_per_bar,
        "duration": round(total_time, 2),
        "total_notes": note_count,
        "instruments": len(midi_instruments),
    }
    return midi, metadata


def save_beat(midi: pretty_midi.PrettyMIDI, metadata: dict, output_dir: str) -> dict:
    """Save MIDI file and render to audio. Returns URLs/paths."""
    beat_id = str(uuid.uuid4())[:8]
    os.makedirs(output_dir, exist_ok=True)

    # Save MIDI
    midi_path = os.path.join(output_dir, f"{beat_id}.mid")
    midi.write(midi_path)

    # Render to WAV using ffmpeg
    wav_path = os.path.join(output_dir, f"{beat_id}.wav")
    mp3_path = os.path.join(output_dir, f"{beat_id}.mp3")
    os.system(f'ffmpeg -y -i "{midi_path}" "{wav_path}" 2>nul')
    os.system(f'ffmpeg -y -i "{wav_path}" -codec:a libmp3lame -b:a 320k "{mp3_path}" 2>nul')

    # Save metadata
    meta_path = os.path.join(output_dir, f"{beat_id}.json")
    results = {**metadata, "id": beat_id}
    with open(meta_path, "w") as f:
        json.dump(results, f, indent=2)

    sizes = {}
    for ext in ["mid", "wav", "mp3"]:
        p = os.path.join(output_dir, f"{beat_id}.{ext}")
        if os.path.exists(p):
            sizes[ext] = os.path.getsize(p)

    return {"id": beat_id, **metadata, "files": sizes, "paths": {
        "mid": midi_path, "wav": wav_path, "mp3": mp3_path
    }}


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    output_dir = os.path.expanduser(input_data.get("output_dir", "~/Downloads/vybra-beats"))
    midi, metadata = build_beat(input_data)
    result = save_beat(midi, metadata, output_dir)
    print(json.dumps(result, indent=2))
