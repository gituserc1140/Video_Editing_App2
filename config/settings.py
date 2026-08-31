"""Configuration settings for the Rendi Streamlit micro-app."""

import os

RENDI_API_BASE_URL = os.getenv("RENDI_API_BASE_URL", "https://api.rendi.dev")
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "30"))
UPLOAD_TIMEOUT = int(os.getenv("UPLOAD_TIMEOUT", "90"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "3"))
COMMAND_WAIT_TIMEOUT = int(os.getenv("COMMAND_WAIT_TIMEOUT", "300"))
UPLOAD_WAIT_TIMEOUT = int(os.getenv("UPLOAD_WAIT_TIMEOUT", "180"))
