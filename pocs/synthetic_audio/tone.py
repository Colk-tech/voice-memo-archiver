"""Generate a deterministic synthetic audio input without reading source audio."""

import math
import struct
import wave
from pathlib import Path


def generate_tone(path: Path) -> None:
    """Create six seconds of mono 48 kHz PCM; an existing path is never replaced.

    Consecutive two-second sections use 220, 440 and 880 Hz sine waves at
    amplitude 0.15. The caller selects the output location. This writes only
    synthetic input and does not import it into Voice Memos.
    """
    rate = 48_000
    frequencies = (220, 440, 880)
    frames = bytearray()
    for sample in range(rate * 6):
        frequency = frequencies[sample // (rate * 2)]
        value = round(0.15 * 32_767 * math.sin(2 * math.pi * frequency * sample / rate))
        frames.extend(struct.pack("<h", value))
    with path.open("xb") as output, wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(frames)
