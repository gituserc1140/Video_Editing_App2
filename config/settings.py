"""Configuration settings for the Shotstack Streamlit micro-app."""

import os

SHOTSTACK_EDIT_BASE_URL = os.getenv("SHOTSTACK_EDIT_BASE_URL", "https://api.shotstack.io")
SHOTSTACK_INGEST_BASE_URL = os.getenv("SHOTSTACK_INGEST_BASE_URL", "https://api.shotstack.io")
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "30"))
UPLOAD_TIMEOUT = int(os.getenv("UPLOAD_TIMEOUT", "90"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "3"))
RENDER_WAIT_TIMEOUT = int(os.getenv("RENDER_WAIT_TIMEOUT", "300"))
INGEST_WAIT_TIMEOUT = int(os.getenv("INGEST_WAIT_TIMEOUT", "180"))
