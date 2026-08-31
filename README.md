# Rendi Video Editing Micro-App

A Streamlit micro-app for simple, FFmpeg-powered video editing using the
[Rendi](https://apps.make.com/rendi) API (https://api.rendi.dev).

## Repository structure

- `app.py` — Streamlit entrypoint
- `api_client.py` — Rendi API client (`fetch_data()` uploads, submits an FFmpeg command, and polls)
- `ui/` — Streamlit UI form and result rendering
- `static/` — app styling assets
- `config/` — environment-configurable settings
- `README.md` — usage instructions

## Requirements

- Python 3.10+
- A Rendi API key

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
streamlit run app.py
```

## How to use

1. **Enter Rendi API key**
   - Paste your Rendi API key value into the `Rendi API key` field. The app sends it in
     Rendi's `X-API-KEY` request header.

2. **Upload a video**
   - Upload an MP4/MOV/WEBM/M4V source file.

3. **Configure edits**
   - Set `Trim start (seconds)` and `Trim end (seconds)`.
   - Add `Text overlay` (optional).
   - Add an `Optional music URL` (optional, must be a publicly accessible audio URL).

4. **Render video**
   - Click `Render Video`.
   - The app uploads your source using Rendi's direct multipart upload flow
     (`POST /v1/files/init-upload` → part `PUT`s → `POST /v1/files/{file_id}/complete-upload`),
     submits an FFmpeg command via `POST /v1/run-ffmpeg-command`, polls
     `GET /v1/commands/{command_id}` for status, then displays the final video.

5. **Download output**
   - Use the `Download rendered video` link shown after render completion.

## Notes

- Trim end must be greater than trim start.
- The app keeps API key entry in the UI (not hard-coded).
- Polling and timeout behavior can be adjusted via environment variables in `config/settings.py`
  (`RENDI_API_BASE_URL`, `DEFAULT_TIMEOUT`, `UPLOAD_TIMEOUT`, `POLL_INTERVAL_SECONDS`,
  `COMMAND_WAIT_TIMEOUT`, `UPLOAD_WAIT_TIMEOUT`).
