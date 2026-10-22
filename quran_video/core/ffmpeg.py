"""Everything that runs ffmpeg: finding it, reading media length and loudness, and the export command line."""

import array
import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: no console window flashes up per ffmpeg call


class FFmpegError(Exception):
    pass


class LeadAudio(NamedTuple):
    """A piece of another audio file played before the recitation (the Basmala)."""
    file: Path
    start_ms: int
    length_ms: int


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):  # the package is missing or has no binary for this platform
        exe = shutil.which("ffmpeg")
        if not exe:
            raise FFmpegError("ffmpeg not found: install imageio-ffmpeg or put ffmpeg on PATH")
        return exe


def is_video(path: Path | None) -> bool:
    return path is not None and path.suffix.lower() not in IMAGE_EXTS


def media_seconds(path: Path) -> float | None:
    """Length of a video file in seconds (None when it can't be read, or for an image)."""
    out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", out)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def envelope(path: Path) -> list[float]:
    """Loudness of an audio file: mean |sample| per 20 ms frame (timing.ENV_RATE frames per second)."""
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, creationflags=NO_WINDOW).stdout
    x = array.array("h", raw[:len(raw) // 2 * 2])
    return [sum(map(abs, x[i:i + 160])) / 160 for i in range(0, len(x) - 159, 160)]


def build_cmd(exe: str, w: int, h: int, fps: int, audio: Path, a_start_ms: int, dur_ms: int,
              out: Path, background: Path | None = None, crf: int = 20, audio_kbps: int = 192,
              lead: LeadAudio | None = None, freeze: bool = False) -> list[str]:
    """The ffmpeg command that turns the RGBA frames on stdin and the recitation into an MP4.

    Without `background`, the frames are complete (the theme colour is drawn in them) and are only encoded.
    With one, the frames are the text layer: the image or video is scaled and cropped to cover WxH and the
    text laid over it. A video shorter than the recitation is looped, or with `freeze` its last frame is
    held. Only recitation audio is mapped, so a background video's own sound never reaches the output.

    The video is Constrained Baseline H.264 with AAC stereo at 44.1 kHz. That is the one profile Fedora's
    stock OpenH264 decoder (gstreamer1-plugin-openh264, used by GNOME Videos) plays, and it also plays
    everywhere else; x264 would otherwise default to High Profile with B-frames, which Fedora refuses with
    "H.264 (High Profile) decoder is required". Normalising the audio here covers recitations that are not
    already 44.1 kHz stereo."""
    lead_ms = lead.length_ms if lead else 0
    dur, total = f"{dur_ms / 1000:.3f}", f"{(dur_ms + lead_ms) / 1000:.3f}"
    if background is None:
        bg_in, video_chain = [], "[0:v]format=yuv420p[v]"
    else:
        if not Path(background).is_file():
            raise FFmpegError(f"Background file not found: {background}")
        cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps}"
        if not is_video(Path(background)):
            bg_in = ["-loop", "1", "-framerate", str(fps), "-i", str(background)]
            bg_chain = cover
        else:
            loop = [] if freeze else ["-stream_loop", "-1"]
            bg_in = [*loop, "-an", "-threads", "2", "-i", str(background)]  # -an: ignore its audio
            bg_chain = cover + (",tpad=stop_mode=clone:stop=-1" if freeze else "")
        video_chain = f"[0:v]{bg_chain}[bg];[bg][1:v]overlay=shortest=1:format=auto,format=yuv420p[v]"
    # Inputs, in order: the background (if any), the frames on stdin, the recitation, the Basmala (if any).
    audio_in = 2 if background is not None else 1
    # With a Basmala, its audio plays first, then the verses. Only recitation audio is ever mapped.
    norm = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
    audio_chain = (f";[{audio_in + 1}:a]{norm}[ba];[{audio_in}:a]{norm}[ma];[ba][ma]concat=n=2:v=0:a=1[a]"
                   if lead else "")
    return [
        exe, "-y", "-hide_banner", "-loglevel", "error",
        *bg_in,
        "-thread_queue_size", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
        "-ss", f"{a_start_ms / 1000:.3f}", "-t", dur, "-i", str(audio),
        *(["-ss", f"{lead.start_ms / 1000:.3f}", "-t", f"{lead.length_ms / 1000:.3f}", "-i", str(lead.file)]
          if lead else []),
        "-filter_complex", video_chain + audio_chain,
        "-map", "[v]", "-map", "[a]" if lead else f"{audio_in}:a",
        # Two encoder threads and short queues keep ffmpeg near 500 MB instead of 950 MB, at no cost in speed.
        # Constrained Baseline (no B-frames, no CABAC) so the stock Fedora OpenH264 decoder can play it.
        "-threads", "2", "-c:v", "libx264", "-profile:v", "baseline", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", f"{audio_kbps}k", "-ar", "44100", "-ac", "2", "-t", total,
        "-movflags", "+faststart",
        "-f", "mp4", str(out),
    ]
