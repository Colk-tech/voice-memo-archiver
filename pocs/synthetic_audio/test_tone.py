"""Verify synthetic PCM format, tone segments and safe output creation."""

import struct
import wave
from pathlib import Path

import pytest

from pocs.synthetic_audio.tone import generate_tone


def test_format_and_segments(tmp_path: Path) -> None:
    target = tmp_path / "synthetic.wav"
    generate_tone(target)
    with wave.open(str(target), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 48_000
        assert audio.getnframes() == 288_000
        assert audio.getcomptype() == "NONE"
        data = audio.readframes(audio.getnframes())
    samples = struct.unpack("<288000h", data)
    assert max(samples) == 4_915
    assert min(samples) == -4_915
    for index, frequency in enumerate((220, 440, 880)):
        segment = samples[index * 96_000 : (index + 1) * 96_000]
        rising = sum(a <= 0 < b for a, b in zip(segment, segment[1:], strict=False))
        assert rising == frequency * 2


def test_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    generate_tone(first)
    generate_tone(second)
    assert first.read_bytes() == second.read_bytes()


def test_nonoverwrite(tmp_path: Path) -> None:
    target = tmp_path / "existing.wav"
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        generate_tone(target)
    assert target.read_bytes() == b"existing"
