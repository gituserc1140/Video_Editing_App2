from __future__ import annotations

from pathlib import Path

import streamlit as st

import api_client
from ui import render_editor_form, render_result

st.set_page_config(page_title="Shotstack Video Editor", page_icon="🎬", layout="centered")

css_path = Path(__file__).parent / "static" / "styles.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

state = render_editor_form()

if state["submitted"]:
    if not state["api_key"]:
        st.error("Please enter your Shotstack Production API key.")
    elif state["video_file"] is None:
        st.error("Please upload a video file.")
    elif state["trim_end"] <= state["trim_start"]:
        st.error("Trim end must be greater than trim start.")
    else:
        with st.spinner("Uploading and rendering video..."):
            try:
                result = api_client.fetch_data(
                    api_key=state["api_key"],
                    video_bytes=state["video_file"].getvalue(),
                    trim_start=state["trim_start"],
                    trim_end=state["trim_end"],
                    text_overlay=state["text_overlay"],
                    music_url=state["music_url"],
                )
            except Exception as exc:
                st.error(f"Render request failed: {exc}")
            else:
                render_result(result)
else:
    st.info("Enter your Production API key, upload a video, configure edits, then click Render Video.")
