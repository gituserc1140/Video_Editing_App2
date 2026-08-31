# Shotstack Video Editing Micro-App

A Streamlit micro-app for simple Shotstack-powered video editing using the Template_App_Private-style structure.

## Repository structure

- `app.py` — Streamlit entrypoint
- `api_client.py` — Shotstack API client (`fetch_data()` uploads, renders, polls)
- `ui/` — Streamlit UI form and result rendering
- `static/` — app styling assets
- `config/` — environment-configurable settings
- `README.md` — usage instructions

## Requirements

- Python 3.10+
- A Shotstack **Production** API key

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
streamlit run app.py
```

## How to use

1. **Enter Production API key**
   - Paste your Shotstack Production API key into the `Shotstack Production API key` field.

2. **Upload a video**
   - Upload an MP4/MOV/WEBM/M4V source file.

3. **Configure edits**
   - Set `Trim start (seconds)` and `Trim end (seconds)`.
   - Add `Text overlay` (optional).
   - Add an `Optional music URL` (optional, must be a publicly accessible audio URL).

4. **Render video**
   - Click `Render Video`.
   - The app uploads your source to Shotstack Ingest, submits a Shotstack render timeline, polls render status, then displays the final video.
   - Render submission uses `POST https://api.shotstack.io/edit/v1/render`; status polling uses `GET /edit/v1/render/{render_id}`. Opening `/edit/v1/render` in a browser sends a GET request and returns a “Not found” response.

5. **Download output**
   - Use the `Download rendered video` link shown after render completion.

## Notes

- Trim end must be greater than trim start.
- The app keeps API key entry in the UI (not hard-coded).
- Polling and timeout behavior can be adjusted via environment variables in `config/settings.py`.
