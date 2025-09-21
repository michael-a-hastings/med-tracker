# med-tracker

## Music Video Generator Toolkit

This repository now includes two convenient ways to build WinAmp-inspired music videos with scrolling lyrics:

### 1. Interactive command-line generator
1. Ensure Python 3.9+ is installed along with the required packages:
   ```bash
   pip install moviepy numpy pillow
   ```
2. Launch the generator and follow the prompts for audio, tags, and lyrics:
   ```bash
   python music_video_generator.py
   ```
3. On success the script prints a JSON payload describing the rendered video, its metadata, thumbnail (if available), and diagnostic logs. The video and thumbnail are saved inside the `outputs/` directory.

### 2. Local web UI for rapid iteration
1. Install the additional UI dependency:
   ```bash
   pip install flask
   ```
2. Start the development server:
   ```bash
   python music_video_app.py
   ```
3. Open <http://127.0.0.1:5000> in your browser. Upload an MP3/WAV file, pick mood & genre tags from the curated lists (or supply custom ones), and paste or upload the song lyrics. Submissions render a music video behind the scenes and surface download links once finished. Assets are stored under `web_outputs/`, while uploaded files live in `web_uploads/` during the session.

### Expanded tag catalog
The mood/genre selector now spans curated collections across Mood, Energy, Genre, Era & Style, and Occasion categories. These tags seed the visual palette and help tailor each render’s look and feel. You can mix preset selections with freeform tags in both the CLI and web UI.

### Development notes
- Both interfaces share the same `generate_music_video` engine and validation logic, ensuring consistent output regardless of workflow.
- Error handling captures missing inputs, unsupported formats, and lyric parsing issues, surfacing helpful feedback in terminal logs or browser flash messages.
- The helper directories (`outputs/`, `web_uploads/`, `web_outputs/`) are created automatically if absent.
