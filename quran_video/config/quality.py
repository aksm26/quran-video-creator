"""Output quality presets: resolution scale, x264 CRF (lower = better) and audio bitrate."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Quality:
    name: str
    scale: float  # of the format's size (1080x1920 and so on)
    crf: int
    audio_kbps: int


QUALITIES: dict[str, Quality] = {q.name: q for q in (
    Quality("Very high", 1.0, 16, 256),
    Quality("High", 1.0, 20, 192),
    Quality("Medium", 0.75, 24, 128),
    Quality("Low", 0.5, 28, 96),
    Quality("Very low", 0.4, 34, 64),
)}
DEFAULT_QUALITY = "High"


def scaled_size(w: int, h: int, scale: float) -> tuple[int, int]:
    """Both sides even, as H.264 with yuv420p requires."""
    return round(w * scale / 2) * 2, round(h * scale / 2) * 2
