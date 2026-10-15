"""Output formats. Adding a format is one line."""

FORMATS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),  # Reels, Shorts, TikTok
    "16:9": (1920, 1080),  # YouTube
    "1:1": (1080, 1080),  # Instagram/Facebook feed
    "4:5": (1080, 1350),  # Instagram feed portrait
}
DEFAULT_FORMAT = "9:16"

# Shown next to each format.
FORMAT_NOTES: dict[str, str] = {
    "9:16": "Reels, Shorts, TikTok",
    "16:9": "YouTube",
    "1:1": "Instagram and Facebook feed",
    "4:5": "Instagram feed",
}
