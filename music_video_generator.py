"""Simple music video generator that combines a sound-reactive visualizer with scrolling lyrics.

This script prompts the user for:
- an audio file (MP3 or WAV)
- mood/genre tags (preset selections or custom input)
- song lyrics (plain text or LRC-style time-coded text)

It outputs a stylized music video with:
- an animated, audio-reactive visualizer reminiscent of WinAmp
- synchronized, continuously scrolling lyrics overlay

The resulting video details are printed as JSON with metadata and log entries.
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

import numpy as np
from moviepy.editor import AudioFileClip, VideoClip
from PIL import Image, ImageDraw, ImageFont


SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav"}

# Curated collections of tags to help shape the generated visual aesthetic.
PRESET_TAG_CATEGORIES = {
    "Mood": [
        "uplifting",
        "melancholic",
        "dreamy",
        "moody",
        "hopeful",
        "romantic",
        "dramatic",
        "chill",
        "bittersweet",
        "introspective",
    ],
    "Energy": [
        "energetic",
        "high-energy",
        "slow-burn",
        "downtempo",
        "anthemic",
        "groovy",
        "pulsing",
        "laid-back",
        "soaring",
        "minimal",
    ],
    "Genre": [
        "electronic",
        "synthwave",
        "lo-fi",
        "hip-hop",
        "trap",
        "r&b",
        "rock",
        "alt-rock",
        "metal",
        "punk",
        "pop",
        "indie-pop",
        "folk",
        "acoustic",
        "country",
        "jazz",
        "soul",
        "classical",
        "ambient",
        "world",
    ],
    "Era & Style": [
        "retro",
        "80s",
        "90s",
        "y2k",
        "futuristic",
        "cyberpunk",
        "psychedelic",
        "cinematic",
        "festival",
        "club",
    ],
    "Occasion": [
        "sunset",
        "night-drive",
        "focus",
        "celebration",
        "workout",
        "party",
        "meditation",
        "study",
        "wedding",
        "breakup",
    ],
}

FLATTENED_PRESET_TAGS = [
    (category, tag)
    for category, tags in PRESET_TAG_CATEGORIES.items()
    for tag in tags
]
DEFAULT_RESOLUTION = (1280, 720)
DEFAULT_FPS = 30
AUDIO_SAMPLING_RATE = 11025


@dataclass
class LyricLine:
    text: str
    start: float
    end: float

    @property
    def center(self) -> float:
        return (self.start + self.end) / 2.0


class GenerationError(RuntimeError):
    """Raised when music video generation fails."""


def prompt_audio_file(logs: List[str]) -> Path:
    """Prompt the user for an audio file path and validate it."""
    while True:
        try:
            audio_input = input("Enter the path to the audio file (MP3 or WAV): ").strip().strip('"')
        except EOFError:
            raise GenerationError("Audio input aborted by user.")

        if not audio_input:
            logs.append("No audio path provided; prompting again.")
            print("Audio path cannot be empty. Please try again.\n")
            continue

        audio_path = Path(audio_input).expanduser()
        if not audio_path.exists():
            logs.append(f"Audio file not found at {audio_path!s}.")
            print(f"No file found at '{audio_path}'. Please provide a valid MP3 or WAV file.\n")
            continue

        if audio_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            logs.append(f"Unsupported audio format: {audio_path.suffix}.")
            print("Unsupported audio format. Please provide an MP3 or WAV file.\n")
            continue

        logs.append(f"Audio file validated: {audio_path.name}.")
        return audio_path


def prompt_mood_tags(logs: List[str]) -> List[str]:
    """Prompt for mood/genre tags, allowing preset selections or custom input."""
    print("\nSelect mood/genre tags that describe the song. You can:")
    print("  - Enter numbers (comma or space separated) from the preset list below")
    print("  - Mix preset numbers with custom tags (e.g. '1, 5, ethereal, sunset')")
    print("Preset options:")
    flattened = list(enumerate(FLATTENED_PRESET_TAGS, start=1))
    for idx, (category, tag) in flattened:
        print(f"  {idx:>2}. [{category}] {tag}")

    while True:
        try:
            tag_input = input("Enter your selection: ").strip()
        except EOFError:
            raise GenerationError("Tag input aborted by user.")

        if not tag_input:
            logs.append("Empty tag input received.")
            print("Please provide at least one tag describing the mood/genre.\n")
            continue

        parts = [part.strip() for part in re.split(r"[,\s]+", tag_input) if part.strip()]
        selected_tags: List[str] = []
        invalid_selection = False

        for part in parts:
            if part.isdigit():
                index = int(part)
                if not 1 <= index <= len(flattened):
                    logs.append(f"Invalid tag index selected: {index}.")
                    print(f"'{index}' is not a valid option. Please try again.\n")
                    invalid_selection = True
                    break
                selected_tags.append(flattened[index - 1][1])
            else:
                selected_tags.append(part)

        if invalid_selection:
            continue

        if not selected_tags:
            logs.append("No tags parsed from selection input.")
            print("Could not parse any tags from the input. Please try again.\n")
            continue

        unique_tags: List[str] = []
        seen = set()
        for tag in selected_tags:
            normalized = tag.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            unique_tags.append(normalized)

        if not unique_tags:
            logs.append("Tag normalization removed all selections.")
            print("Tags could not be interpreted. Please try again.\n")
            continue

        logs.append(f"Tags selected: {unique_tags}.")
        return unique_tags


def prompt_lyrics(logs: List[str]) -> str:
    """Prompt the user to provide lyrics as plain text or via file import."""
    print("\nProvide the song lyrics. Options:")
    print("  1. Paste or type the lyrics directly (supports LRC timestamps like [mm:ss.xx])")
    print("  2. Enter the path to a text file containing the lyrics")

    while True:
        try:
            mode = input("Type 'direct' to paste or 'file' to load from disk: ").strip().lower()
        except EOFError:
            raise GenerationError("Lyrics input aborted by user.")

        if mode not in {"direct", "file"}:
            logs.append(f"Invalid lyrics input mode: {mode}.")
            print("Please enter either 'direct' or 'file'.\n")
            continue

        if mode == "file":
            try:
                path_input = input("Enter the path to the lyrics text file: ").strip().strip('"')
            except EOFError:
                raise GenerationError("Lyrics file input aborted by user.")

            lyrics_path = Path(path_input).expanduser()
            if not lyrics_path.exists() or not lyrics_path.is_file():
                logs.append(f"Lyrics file not found: {lyrics_path!s}.")
                print("Lyrics file not found. Please try again.\n")
                continue

            lyrics_text = lyrics_path.read_text(encoding="utf-8", errors="ignore").strip()
            if not lyrics_text:
                logs.append(f"Lyrics file {lyrics_path.name} is empty.")
                print("The selected file is empty. Please choose another file or paste the lyrics.\n")
                continue

            logs.append(f"Loaded lyrics from file: {lyrics_path.name}.")
            return lyrics_text

        # Direct input mode
        print("\nPaste the lyrics below. Submit an empty line to finish input:\n")
        lines: List[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                raise GenerationError("Lyrics entry aborted by user.")

            if line == "":
                break
            lines.append(line)

        lyrics_text = "\n".join(lines).strip()
        if not lyrics_text:
            logs.append("Direct lyrics input was empty.")
            print("Lyrics cannot be empty. Please try again.\n")
            continue

        logs.append("Lyrics captured via direct input.")
        return lyrics_text


def parse_lrc_timestamp(token: str) -> float:
    """Convert an LRC timestamp token (mm:ss.xx) into seconds."""
    minute_str, second_str = token.split(":", maxsplit=1)
    minutes = int(minute_str)
    seconds = float(second_str)
    return minutes * 60 + seconds


def parse_lyrics(text: str, duration: float, logs: List[str]) -> List[LyricLine]:
    """Parse lyrics text into a list of LyricLine objects with timing information."""
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        raise GenerationError("Lyrics parsing failed: no usable lines found.")

    timestamp_pattern = re.compile(r"\[(\d+:[0-9.]+)\]")
    timed_entries: List[Tuple[float, str]] = []

    for raw in raw_lines:
        timestamps = timestamp_pattern.findall(raw)
        lyric_text = timestamp_pattern.sub("", raw).strip()
        if timestamps:
            if not lyric_text:
                lyric_text = "♪"
            for ts in timestamps:
                try:
                    timed_entries.append((parse_lrc_timestamp(ts), lyric_text))
                except ValueError:
                    logs.append(f"Invalid timestamp '{ts}' encountered in lyrics; ignoring.")
        else:
            timed_entries.append((math.nan, raw))

    has_valid_timestamps = any(not math.isnan(start) for start, _ in timed_entries)

    if has_valid_timestamps:
        filtered_entries = [(start, text) for start, text in timed_entries if not math.isnan(start)]
        if not filtered_entries:
            raise GenerationError("All lyrics timestamps were invalid; unable to continue.")
        filtered_entries.sort(key=lambda item: item[0])

        lyric_lines: List[LyricLine] = []
        for index, (start_time, line_text) in enumerate(filtered_entries):
            if index + 1 < len(filtered_entries):
                end_time = filtered_entries[index + 1][0]
            else:
                end_time = duration
            end_time = max(start_time + 0.1, min(end_time, duration))
            lyric_lines.append(LyricLine(text=line_text, start=start_time, end=end_time))
        logs.append("Parsed time-synced lyrics using LRC timestamps.")
        return lyric_lines

    # No timestamps: distribute evenly across the song duration.
    evenly_spaced_lines = [text for _, text in timed_entries]
    segment_length = duration / len(evenly_spaced_lines)
    lyric_lines = []
    for idx, line_text in enumerate(evenly_spaced_lines):
        start_time = idx * segment_length
        end_time = min(duration, start_time + segment_length)
        lyric_lines.append(LyricLine(text=line_text, start=start_time, end=end_time))

    logs.append("No timestamps detected; distributed lyrics evenly across the track duration.")
    return lyric_lines


def smooth_signal(signal: np.ndarray, window_size: int) -> np.ndarray:
    """Apply a simple moving average to smooth a 1D signal."""
    if window_size <= 1:
        return signal
    window = np.ones(window_size) / float(window_size)
    return np.convolve(signal, window, mode="same")


def prepare_amplitude_profile(audio_clip: AudioFileClip, logs: List[str]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Generate amplitude and pseudo-EQ bands for the audio clip."""
    logs.append("Extracting audio samples for visualization cues.")
    samples = audio_clip.to_soundarray(fps=AUDIO_SAMPLING_RATE)
    if samples.ndim == 2:
        mono = samples.mean(axis=1)
    else:
        mono = samples

    amplitude = np.abs(mono)
    if amplitude.max() > 0:
        amplitude = amplitude / amplitude.max()

    # Generate three smoothed variants to simulate EQ bands.
    low_band = smooth_signal(amplitude, max(1, int(AUDIO_SAMPLING_RATE * 0.25)))
    mid_band = smooth_signal(amplitude, max(1, int(AUDIO_SAMPLING_RATE * 0.1)))
    high_band = smooth_signal(amplitude, max(1, int(AUDIO_SAMPLING_RATE * 0.03)))

    low_band = np.clip(low_band, 0, 1)
    mid_band = np.clip(mid_band, 0, 1)
    high_band = np.clip(high_band, 0, 1)

    duration = audio_clip.duration

    def normalize(arr: np.ndarray) -> np.ndarray:
        max_val = arr.max() if arr.size else 1.0
        return arr / max(max_val, 1e-6)

    logs.append("Generated visualization cues using smoothed amplitude bands.")
    return normalize(low_band), normalize(mid_band), normalize(high_band), duration


def amplitude_lookup(signal: np.ndarray, t: float) -> float:
    """Retrieve amplitude at a specific timestamp from the normalized profile."""
    index = int(min(len(signal) - 1, max(0, round(t * AUDIO_SAMPLING_RATE))))
    return float(signal[index])


def build_visualizer_frame_generator(
    low_band: np.ndarray,
    mid_band: np.ndarray,
    high_band: np.ndarray,
    lyric_lines: Sequence[LyricLine],
    duration: float,
    resolution: Tuple[int, int],
    logs: List[str],
    tags: Sequence[str],
) -> Callable[[float], np.ndarray]:
    width, height = resolution
    x_coords = np.linspace(0, 2 * np.pi, width)
    seed_input = "|".join(tags) if tags else "default"
    palette_seed = abs(hash(seed_input)) % (2 ** 32)
    rng = np.random.RandomState(palette_seed)
    base_palette = rng.rand(3)
    logs.append(
        "Visualizer color palette seeded from tags: "
        f"{', '.join(tags) if tags else 'default palette'}."
    )

    # Load fonts once to avoid repeated disk lookups.
    def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for path in font_paths:
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        logs.append("Falling back to default PIL font for lyrics overlay.")
        return ImageFont.load_default()

    primary_font = load_font(48)
    secondary_font = load_font(36)

    line_spacing = 60
    scroll_speed = line_spacing * 1.2  # pixels per second offset relative to lyric center

    def frame_function(t: float) -> np.ndarray:
        base = np.zeros((height, width, 3), dtype=np.float32)

        low = amplitude_lookup(low_band, t)
        mid = amplitude_lookup(mid_band, t)
        high = amplitude_lookup(high_band, t)

        freq_low = 1.5 + low * 3.0
        freq_mid = 2.0 + mid * 4.0
        freq_high = 3.0 + high * 5.0

        y_coords = np.linspace(0, 2 * np.pi, height).reshape(-1, 1)
        layer1 = (np.sin(freq_low * x_coords + t * 2) + 1) / 2
        layer2 = (np.sin(freq_mid * y_coords + t * 1.5) + 1) / 2
        layer3 = (np.sin(freq_high * (x_coords + y_coords) + t * 3) + 1) / 2

        base[:, :, 0] = layer1 * (0.6 + 0.4 * base_palette[0])
        base[:, :, 1] = layer2 * (0.6 + 0.4 * base_palette[1])
        base[:, :, 2] = layer3 * (0.6 + 0.4 * base_palette[2])

        # Add waveforms inspired by WinAmp style
        num_lines = 3
        line_colors = [
            (1.0, 0.8, 0.2),
            (0.2, 0.9, 1.0),
            (1.0, 0.3, 0.8),
        ]
        overlay = Image.fromarray((np.clip(base, 0, 1) * 255).astype(np.uint8)).convert("RGBA")
        overlay_draw = ImageDraw.Draw(overlay, "RGBA")

        for line_idx in range(num_lines):
            phase_offset = t * (1.5 + line_idx * 0.5)
            amplitude_scale = 120 * (0.4 + amplitude_lookup(mid_band, max(0, t - 0.1 * line_idx)))
            points: List[Tuple[float, float]] = []
            for x in range(width):
                progress = x / width
                sample_time = min(duration, max(0.0, t - (1 - progress) * 0.4))
                amp_value = amplitude_lookup(high_band, sample_time)
                y = (
                    height / 2
                    + math.sin(progress * (3 + line_idx) * math.pi + phase_offset)
                    * amplitude_scale
                    * (0.5 + amp_value)
                )
                points.append((x, y))
            color = line_colors[line_idx % len(line_colors)]
            rgba_color = (
                int(255 * color[0]),
                int(255 * color[1]),
                int(255 * color[2]),
                int(180 * (0.5 + low * 0.5)),
            )
            overlay_draw.line(points, fill=rgba_color, width=4)

        # Lyrics overlay with scrolling effect
        current_image = overlay
        text_draw = ImageDraw.Draw(current_image, "RGBA")
        active_window = line_spacing * 4
        for line in lyric_lines:
            offset = (line.center - t) * scroll_speed
            y_position = height / 2 + offset
            if y_position < -active_window or y_position > height + active_window:
                continue

            is_active = line.start <= t <= line.end
            font = primary_font if is_active else secondary_font
            fill_color = (255, 255, 255, 255) if is_active else (220, 220, 220, 200)
            glow_color = (0, 0, 0, 160)

            text = line.text
            text_width, text_height = text_draw.textsize(text, font=font)
            x_position = (width - text_width) / 2

            # Draw subtle glow behind the text for readability.
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    text_draw.text((x_position + dx, y_position + dy), text, font=font, fill=glow_color)

            text_draw.text((x_position, y_position), text, font=font, fill=fill_color)

        return np.array(current_image.convert("RGB"))

    return frame_function


def generate_music_video(
    audio_path: Path,
    tags: Sequence[str],
    lyrics_text: str,
    logs: List[str],
    resolution: Tuple[int, int] = DEFAULT_RESOLUTION,
    fps: int = DEFAULT_FPS,
) -> Tuple[str, float, str, int, str | None]:
    """Create the music video and return metadata including output locations."""
    try:
        audio_clip = AudioFileClip(str(audio_path))
    except Exception as exc:  # pragma: no cover - defensive logging
        raise GenerationError(f"Failed to load audio file: {exc}")

    low_band, mid_band, high_band, duration = prepare_amplitude_profile(audio_clip, logs)
    lyrics = parse_lyrics(lyrics_text, duration, logs)

    frame_function = build_visualizer_frame_generator(
        low_band=low_band,
        mid_band=mid_band,
        high_band=high_band,
        lyric_lines=lyrics,
        duration=duration,
        resolution=resolution,
        logs=logs,
        tags=tags,
    )

    video_clip = VideoClip(make_frame=frame_function, duration=duration)
    video_clip = video_clip.set_audio(audio_clip)

    outputs_dir = Path("outputs")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    video_filename = f"music_video_{timestamp}.mp4"
    video_path = outputs_dir / video_filename

    logs.append(f"Rendering video to {video_path!s} at {fps} fps.")
    try:
        video_clip.write_videofile(
            str(video_path),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            audio_bitrate="192k",
            threads=4,
            verbose=False,
            logger=None,
        )
    finally:
        video_clip.close()
        audio_clip.close()

    # Generate thumbnail at 1 second mark or middle if shorter.
    thumbnail_path: Path | None = None
    try:
        thumbnail_path = outputs_dir / f"{video_path.stem}_thumbnail.jpg"
        clip_for_thumb = VideoClip(make_frame=frame_function, duration=duration)
        snapshot_time = min(1.0, duration / 2)
        clip_for_thumb.save_frame(str(thumbnail_path), t=snapshot_time)
        clip_for_thumb.close()
        logs.append(f"Thumbnail saved to {thumbnail_path!s}.")
    except Exception as exc:  # pragma: no cover - best effort thumbnail
        logs.append(f"Thumbnail generation failed: {exc}.")

    resolution_text = f"{resolution[0]}x{resolution[1]}"
    return str(video_path), duration, resolution_text, fps, str(thumbnail_path) if thumbnail_path else None


def create_generation_payload(
    audio_path: Path,
    tags: Sequence[str],
    lyrics_text: str,
    logs: List[str] | None = None,
    *,
    resolution: Tuple[int, int] = DEFAULT_RESOLUTION,
    fps: int = DEFAULT_FPS,
    outputs_dir: Path | None = None,
) -> dict:
    """Convenience helper to produce the validated JSON payload."""

    working_logs: List[str] = logs if logs is not None else []
    (
        video_file_url,
        duration_seconds,
        resolution_text,
        frame_rate,
        thumbnail_url,
    ) = generate_music_video(
        audio_path=audio_path,
        tags=tags,
        lyrics_text=lyrics_text,
        logs=working_logs,
        resolution=resolution,
        fps=fps,
        outputs_dir=outputs_dir,
    )

    payload = {
        "video_file_url": video_file_url,
        "video_metadata": {
            "duration_seconds": round(duration_seconds, 2),
            "resolution": resolution_text,
            "frame_rate": frame_rate,
        },
    }

    if thumbnail_url:
        payload["thumbnail_url"] = thumbnail_url
    if working_logs:
        payload["logs"] = working_logs

    return validate_output(payload, working_logs)


def validate_output(payload: dict, logs: List[str]) -> dict:
    """Ensure the output JSON includes required fields."""
    errors = []
    if not payload.get("video_file_url"):
        errors.append("Missing video file URL.")
    metadata = payload.get("video_metadata") or {}
    if "duration_seconds" not in metadata or metadata["duration_seconds"] <= 0:
        errors.append("Invalid or missing duration in metadata.")
    if "resolution" not in metadata or not metadata["resolution"]:
        errors.append("Missing resolution in metadata.")
    if "frame_rate" not in metadata or metadata["frame_rate"] <= 0:
        errors.append("Invalid frame rate in metadata.")

    if errors:
        logs.extend(errors)
        payload.setdefault("logs", []).extend(errors)
    return payload


def main() -> None:
    logs: List[str] = []

    try:
        audio_path = prompt_audio_file(logs)
        tags = prompt_mood_tags(logs)
        lyrics_text = prompt_lyrics(logs)
        logs.append(f"Mood/genre tags set to: {tags}.")

        payload = create_generation_payload(
            audio_path=audio_path,
            tags=tags,
            lyrics_text=lyrics_text,
            logs=logs,
        )
        print(json.dumps(payload, indent=2))

    except GenerationError as exc:
        logs.append(str(exc))
        payload = {
            "video_file_url": "",
            "video_metadata": {
                "duration_seconds": 0,
                "resolution": "",
                "frame_rate": 0,
            },
            "logs": logs,
        }
        payload = validate_output(payload, logs)
        print(json.dumps(payload, indent=2))
        sys.exit(1)
    except Exception as exc:  # pragma: no cover - unexpected errors logged gracefully
        logs.append(f"Unexpected error: {exc}")
        payload = {
            "video_file_url": "",
            "video_metadata": {
                "duration_seconds": 0,
                "resolution": "",
                "frame_rate": 0,
            },
            "logs": logs,
        }
        payload = validate_output(payload, logs)
        print(json.dumps(payload, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
