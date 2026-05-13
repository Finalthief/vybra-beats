"""
Chiptune audio renderer — generates WAV audio directly from note data.
No external dependencies beyond Python stdlib + numpy alternative (pure math).
Square waves, triangle waves, noise for authentic NES-style chiptune.
"""
import math
import struct
import wave
from typing import List, Tuple

SAMPLE_RATE = 44100
MAX_VOLUME = 0.3

# NES duty cycles (12.5%, 25%, 50%, 75%)
def square_wave(t: float, freq: float, duty: float = 0.5, length: float = 0) -> float:
    """Generate a square wave sample at time t with given frequency and duty cycle."""
    if freq <= 0:
        return 0.0
    period = 1.0 / freq
    phase = (t % period) / period
    return 1.0 if phase < duty else -1.0


def triangle_wave(t: float, freq: float) -> float:
    """Generate a triangle wave sample."""
    if freq <= 0:
        return 0.0
    period = 1.0 / freq
    phase = (t % period) / period
    return 4.0 * abs(phase - 0.5) - 1.0


def noise_sample(t: float, seed: int = 0) -> float:
    """Generate a simple noise sample (pseudo-random)."""
    # Use a simple LFSR-like noise
    val = math.sin(t * 12345.67 + seed * 789.0) * 10000
    return ((int(val) % 65535) / 32768.0) - 1.0


def midi_to_freq(pitch: int) -> float:
    """Convert MIDI note number to frequency in Hz."""
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def render_note(
    pitch: int,
    start_time: float,
    duration: float,
    velocity: int = 100,
    wave_type: str = "square",
    duty_cycle: float = 0.5,
    sample_rate: int = SAMPLE_RATE,
) -> List[float]:
    """Render a single note to a float waveform."""
    freq = midi_to_freq(pitch)
    num_samples = int(duration * sample_rate)
    start_sample = int(start_time * sample_rate)
    
    # Pad with leading silence
    samples = [0.0] * (start_sample + num_samples)
    
    amp = (velocity / 127.0) * MAX_VOLUME
    # Add slight attack/decay envelope
    attack = int(0.01 * sample_rate)
    decay = int(0.05 * sample_rate)
    
    for i in range(num_samples):
        t = start_time + i / sample_rate
        env = 1.0
        if i < attack:
            env = i / attack
        elif i > num_samples - decay:
            env = (num_samples - i) / decay
        
        if wave_type == "square":
            val = square_wave(t, freq, duty_cycle)
        elif wave_type == "triangle":
            val = triangle_wave(t, freq)
        elif wave_type == "noise":
            val = noise_sample(t, pitch)
        else:
            val = square_wave(t, freq, 0.5)
        
        samples[start_sample + i] = val * amp * env
    
    return samples


def mix_tracks(tracks: List[List[float]]) -> List[float]:
    """Mix multiple tracks together, clipping prevention."""
    max_len = max(len(t) for t in tracks)
    mixed = [0.0] * max_len
    
    for track in tracks:
        for i in range(len(track)):
            mixed[i] += track[i]
    
    # Soft clip to prevent harsh distortion
    for i in range(len(mixed)):
        if mixed[i] > 1.0:
            mixed[i] = 1.0
        elif mixed[i] < -1.0:
            mixed[i] = -1.0
    
    return mixed


def save_wav(samples: List[float], output_path: str, sample_rate: int = SAMPLE_RATE):
    """Save float samples to WAV file."""
    n_channels = 1
    sampwidth = 2  # 16-bit
    
    with wave.open(output_path, 'w') as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        
        # Convert float to 16-bit int
        for sample in samples:
            int_val = max(-32768, min(32767, int(sample * 32767)))
            wf.writeframes(struct.pack('<h', int_val))


def render_from_midi_notes(
    notes: List[Tuple[int, float, float, int]],  # (pitch, start, duration, velocity)
    wave_type: str = "square",
    duty_cycle: float = 0.5,
    sample_rate: int = SAMPLE_RATE,
) -> List[float]:
    """Take a list of MIDI-like notes and render to waveform."""
    tracks = []
    for pitch, start, duration, velocity in notes[:8]:  # 8-channel limit like NES
        track = render_note(
            pitch=pitch,
            start_time=start,
            duration=duration,
            velocity=velocity,
            wave_type=wave_type,
            duty_cycle=duty_cycle,
            sample_rate=sample_rate,
        )
        tracks.append(track)
    return mix_tracks(tracks)


def midi_pitch_from_note_name(name: str) -> int:
    """Convert note name like 'C4' to MIDI pitch."""
    note_map = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
                'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
                'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11}
    
    name = name.strip()
    note = name[0].upper()
    acc = name[1] if len(name) > 1 and name[1] in '#b' else ''
    octave = int(name[-1])
    return (octave + 1) * 12 + note_map.get(note + acc, 0)