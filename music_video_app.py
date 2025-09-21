"""Lightweight Flask UI for running the music video generator locally."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from flask import Flask, flash, render_template_string, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from music_video_generator import (
    PRESET_TAG_CATEGORIES,
    SUPPORTED_AUDIO_EXTENSIONS,
    GenerationError,
    create_generation_payload,
)

app = Flask(__name__)
app.secret_key = "development-secret-key"

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "web_uploads"
OUTPUT_DIR = BASE_DIR / "web_outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


def _is_allowed_audio(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def _dedupe_tags(tags: List[str]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for tag in tags:
        normalized = tag.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


@app.route("/", methods=["GET", "POST"])
def index():
    logs: List[str] = []
    payload: dict | None = None
    preset_selected = set(request.form.getlist("tags")) if request.method == "POST" else set()
    custom_tags_value = request.form.get("custom_tags", "") if request.method == "POST" else ""
    lyrics_text_value = request.form.get("lyrics_text", "") if request.method == "POST" else ""

    if request.method == "POST":
        audio_file = request.files.get("audio")
        lyric_file = request.files.get("lyrics_file")
        selected_tags = list(preset_selected)

        if custom_tags_value:
            selected_tags.extend(
                tag.strip()
                for tag in custom_tags_value.split(",")
                if tag.strip()
            )

        errors = False

        if not audio_file or audio_file.filename == "":
            flash("Please upload an MP3 or WAV audio file.", "error")
            errors = True
        elif not _is_allowed_audio(audio_file.filename):
            flash("Unsupported audio format. Please upload an MP3 or WAV file.", "error")
            errors = True

        lyrics_text = lyrics_text_value.strip()
        if lyric_file and lyric_file.filename:
            try:
                lyrics_bytes = lyric_file.read()
                lyrics_from_file = lyrics_bytes.decode("utf-8", errors="ignore").strip()
                if lyrics_from_file:
                    lyrics_text = lyrics_from_file
                else:
                    flash("Uploaded lyrics file was empty.", "error")
                    errors = True
            except Exception as exc:
                flash(f"Failed to read lyrics file: {exc}", "error")
                errors = True

        if not lyrics_text:
            flash("Please provide song lyrics (paste into the text area or upload a file).", "error")
            errors = True

        normalized_tags = _dedupe_tags(selected_tags)
        if not normalized_tags:
            flash("Select at least one mood or genre tag.", "error")
            errors = True

        saved_audio_path: Path | None = None
        if not errors:
            filename = secure_filename(audio_file.filename)
            saved_audio_path = UPLOAD_DIR / filename
            audio_file.save(saved_audio_path)

            try:
                payload = create_generation_payload(
                    audio_path=saved_audio_path,
                    tags=normalized_tags,
                    lyrics_text=lyrics_text,
                    logs=logs,
                    outputs_dir=OUTPUT_DIR,
                )
                flash("Video generated successfully!", "success")
            except GenerationError as exc:
                flash(str(exc), "error")
            except Exception as exc:  # pragma: no cover - surface unexpected issues in UI
                flash(f"Unexpected error: {exc}", "error")

        # Update textarea with the resolved lyrics in case they came from a file
        lyrics_text_value = lyrics_text

    payload_json = json.dumps(payload, indent=2) if payload else ""

    video_download_name = None
    thumbnail_download_name = None
    output_root = OUTPUT_DIR.resolve()
    if payload and payload.get("video_file_url"):
        video_path = Path(payload["video_file_url"]).resolve()
        if video_path.is_file() and output_root in video_path.parents:
            video_download_name = video_path.name
    if payload and payload.get("thumbnail_url"):
        thumb_path = Path(payload["thumbnail_url"]).resolve()
        if thumb_path.is_file() and output_root in thumb_path.parents:
            thumbnail_download_name = thumb_path.name

    return render_template_string(
        TEMPLATE,
        categories=PRESET_TAG_CATEGORIES,
        preset_selected=preset_selected,
        custom_tags_value=custom_tags_value,
        lyrics_text_value=lyrics_text_value,
        payload=payload,
        payload_json=payload_json,
        logs=logs,
        video_download_name=video_download_name,
        thumbnail_download_name=thumbnail_download_name,
    )


@app.route("/outputs/<path:filename>")
def download_output(filename: str):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Music Video Generator UI</title>
    <style>
      body {
        font-family: Arial, Helvetica, sans-serif;
        margin: 2rem auto;
        max-width: 960px;
        padding: 0 1.5rem 3rem;
        background: #111;
        color: #f4f4f4;
      }
      h1, h2, h3 {
        font-weight: 600;
        color: #fdfdfd;
      }
      a {
        color: #4fc3f7;
      }
      .panel {
        background: rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
      }
      label {
        display: block;
        margin-top: 0.75rem;
      }
      input[type="file"], input[type="text"], textarea, select {
        width: 100%;
        margin-top: 0.35rem;
        padding: 0.6rem;
        border-radius: 8px;
        border: 1px solid rgba(255, 255, 255, 0.15);
        background: rgba(0, 0, 0, 0.35);
        color: #f4f4f4;
      }
      textarea {
        min-height: 180px;
        resize: vertical;
      }
      button {
        margin-top: 1.5rem;
        padding: 0.75rem 1.5rem;
        border: none;
        border-radius: 999px;
        background: linear-gradient(135deg, #8e2de2, #4a00e0);
        color: #fff;
        font-size: 1rem;
        cursor: pointer;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
      }
      button:hover {
        transform: translateY(-1px);
        box-shadow: 0 12px 20px rgba(142, 45, 226, 0.35);
      }
      fieldset {
        border: none;
        padding: 0;
        margin: 1rem 0;
      }
      .tags-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 0.75rem 1.25rem;
        margin-top: 0.75rem;
      }
      .tag-option {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.45rem 0.65rem;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 999px;
      }
      .flash {
        padding: 0.75rem 1rem;
        border-radius: 8px;
        margin-bottom: 0.75rem;
      }
      .flash.error {
        background: rgba(244, 67, 54, 0.25);
        border: 1px solid rgba(244, 67, 54, 0.5);
      }
      .flash.success {
        background: rgba(76, 175, 80, 0.25);
        border: 1px solid rgba(76, 175, 80, 0.45);
      }
      pre {
        background: rgba(0, 0, 0, 0.4);
        padding: 1rem;
        border-radius: 12px;
        overflow-x: auto;
      }
      .logs {
        font-size: 0.9rem;
        line-height: 1.4;
        margin-top: 1rem;
      }
    </style>
  </head>
  <body>
    <h1>Music Video Generator</h1>
    <div class="panel">
      <p>Run the WinAmp-inspired visualizer locally: upload an audio track, tag its vibe, and provide lyrics to generate a synchronized music video.</p>
      {% with messages = get_flashed_messages(with_categories=True) %}
        {% if messages %}
          {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
          {% endfor %}
        {% endif %}
      {% endwith %}
      <form method="post" enctype="multipart/form-data">
        <label>Audio File (MP3 or WAV)
          <input type="file" name="audio" accept=".mp3,.wav" required>
        </label>

        <fieldset>
          <legend>Select Mood &amp; Genre Tags</legend>
          {% for category, tags in categories.items() %}
            <h3>{{ category }}</h3>
            <div class="tags-grid">
              {% for tag in tags %}
                <label class="tag-option">
                  <input type="checkbox" name="tags" value="{{ tag }}" {% if tag in preset_selected %}checked{% endif %}>
                  <span>{{ tag }}</span>
                </label>
              {% endfor %}
            </div>
          {% endfor %}
        </fieldset>

        <label>Custom Tags (comma separated)
          <input type="text" name="custom_tags" value="{{ custom_tags_value }}" placeholder="e.g. neon, midnight, ethereal">
        </label>

        <label>Lyrics (paste text or upload a .txt/.lrc file)
          <textarea name="lyrics_text" placeholder="Paste song lyrics here">{{ lyrics_text_value }}</textarea>
        </label>
        <input type="file" name="lyrics_file" accept=".txt,.lrc">

        <button type="submit">Generate Music Video</button>
      </form>
    </div>

    {% if payload %}
      <div class="panel">
        <h2>Generation Result</h2>
        <pre>{{ payload_json }}</pre>
        {% if video_download_name %}
          <p><a href="{{ url_for('download_output', filename=video_download_name) }}">Download video</a></p>
        {% endif %}
        {% if thumbnail_download_name %}
          <p><a href="{{ url_for('download_output', filename=thumbnail_download_name) }}">Download thumbnail</a></p>
        {% endif %}
        {% if logs %}
          <div class="logs">
            <h3>Logs</h3>
            <ul>
              {% for entry in logs %}
                <li>{{ entry }}</li>
              {% endfor %}
            </ul>
          </div>
        {% endif %}
      </div>
    {% endif %}
  </body>
</html>
"""


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
