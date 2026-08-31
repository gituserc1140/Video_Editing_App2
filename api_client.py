from __future__ import annotations

import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from config import settings


INGEST_UPLOAD_ENDPOINT = "/ingest/v1/upload"
SOURCE_STATUS_ENDPOINT = "/ingest/v1/sources/{source_id}"
RENDER_ENDPOINT = "/edit/v1/render"


def _extract(data: Any, *paths: str) -> Optional[Any]:
    for path in paths:
        current = data
        ok = True
        for key in path.split("."):
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                ok = False
                break
        if ok and current is not None:
            return current
    return None


def _error_detail(body: Dict[str, Any]) -> Optional[str]:
    error = _extract(body, "response.error", "response.errors", "response.message")
    if isinstance(error, dict):
        parts = []
        name = error.get("name") or error.get("code")
        if name:
            parts.append(str(name))
        details = error.get("details") or error.get("errors")
        if isinstance(details, list):
            for item in details:
                if isinstance(item, dict) and item.get("message"):
                    parts.append(str(item["message"]))
                elif item:
                    parts.append(str(item))
        elif error.get("message"):
            parts.append(str(error["message"]))
        if parts:
            return "; ".join(parts)
    elif isinstance(error, list):
        parts = [str(item.get("message", item)) if isinstance(item, dict) else str(item) for item in error]
        if parts:
            return "; ".join(parts)
    elif isinstance(error, str) and error:
        return error
    elif error is not None:
        return str(error)

    message = _extract(body, "message", "error")
    response_field = body.get("response") if isinstance(body, dict) else None

    if isinstance(response_field, str) and response_field:
        if message and message != response_field:
            return f"{message}: {response_field}"
        return response_field

    return message


def _render_output_url(data: Any) -> Optional[str]:
    url = _extract(
        data,
        "response.url",
        "response.data.url",
        "data.attributes.url",
        "data.url",
        "url",
    )
    if not isinstance(url, str):
        return None

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    edit_api = urlparse(settings.SHOTSTACK_EDIT_BASE_URL)
    if parsed.hostname == edit_api.hostname:
        return None
    return url


def _request(
    base_url: str,
    method: str,
    path: str,
    api_key: str,
    *,
    json_payload: Optional[Dict[str, Any]] = None,
    data: Optional[bytes] = None,
    timeout: Optional[int] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Any:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"x-api-key": api_key.strip(), "Accept": "application/json"}
    if json_payload is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_payload,
            data=data,
            timeout=timeout or settings.DEFAULT_TIMEOUT,
            allow_redirects=False,
        )
    except requests.exceptions.ConnectionError as exc:
        raise requests.exceptions.ConnectionError(
            f"Could not reach {base_url} ({method.upper()} {path}); check your network connection "
            "and that this environment allows outbound requests to the Shotstack API host",
            response=getattr(exc, "response", None),
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise requests.exceptions.Timeout(
            f"Timed out connecting to {base_url} ({method.upper()} {path}); the Shotstack API host "
            "may be unreachable from this environment",
            response=getattr(exc, "response", None),
        ) from exc
    if response.status_code in {301, 302, 303, 307, 308}:
        location = response.headers.get("Location", "an unknown location")
        raise requests.HTTPError(
            f"Shotstack redirected {method.upper()} {path} to {location}; "
            "check that the configured API base URL is the production API host",
            response=response,
        )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = None
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            detail = _error_detail(body)
        if response.status_code == 403:
            mismatch_hint = (
                "This is often caused by a Sandbox API key being used against the Production API "
                "(or vice versa) - confirm the key type matches the configured base URL"
            )
            detail = f"{detail}; {mismatch_hint}" if detail else mismatch_hint
        if detail:
            raise requests.HTTPError(f"{exc} - {detail}", response=response) from exc
        raise
    if not response.text:
        return {}

    try:
        return response.json()
    except ValueError:
        return response.text


def _upload_video_source(api_key: str, video_bytes: bytes) -> str:
    ingest_base = settings.SHOTSTACK_INGEST_BASE_URL
    upload_response = _request(ingest_base, "POST", INGEST_UPLOAD_ENDPOINT, api_key)

    upload_url = _extract(upload_response, "data.attributes.url", "data.url", "response.url", "url")
    source_id = _extract(upload_response, "data.id", "response.id", "id")

    if not upload_url or not source_id:
        raise RuntimeError("Could not retrieve Shotstack upload URL or source ID")

    put_response = requests.put(
        upload_url,
        data=video_bytes,
        headers={"Content-Type": "application/octet-stream"},
        timeout=settings.UPLOAD_TIMEOUT,
    )
    put_response.raise_for_status()

    # Wait for source to become ready for edit API use.
    deadline = time.time() + settings.INGEST_WAIT_TIMEOUT
    while time.time() < deadline:
        source_resp = _request(
            ingest_base,
            "GET",
            SOURCE_STATUS_ENDPOINT.format(source_id=source_id),
            api_key,
            timeout=settings.DEFAULT_TIMEOUT,
        )
        status = str(_extract(source_resp, "data.attributes.status", "data.status", "response.status", "status") or "").lower()
        if status == "ready":
            return str(source_id)
        if status in {"failed", "error"}:
            message = _extract(source_resp, "data.attributes.error", "message") or "Source ingest failed"
            raise RuntimeError(str(message))
        time.sleep(settings.POLL_INTERVAL_SECONDS)

    raise TimeoutError("Timed out waiting for uploaded source to become ready")


def _build_timeline_payload(
    source_id: str,
    trim_start: float,
    trim_end: float,
    text_overlay: str,
    music_url: Optional[str],
) -> Dict[str, Any]:
    if trim_end <= trim_start:
        raise ValueError("Trim end must be greater than trim start")

    clip_length = round(trim_end - trim_start, 3)

    video_clip: Dict[str, Any] = {
        "asset": {"type": "video", "src": f"shotstack://source/{source_id}/original"},
        "start": 0,
        "length": clip_length,
        "trim": round(trim_start, 3),
    }

    tracks = [{"clips": [video_clip]}]

    if text_overlay:
        text_clip = {
            "asset": {
                "type": "title",
                "text": text_overlay,
                "style": "minimal",
                "size": "medium",
            },
            "start": 0,
            "length": min(clip_length, 5),
            "position": "bottom",
        }
        tracks.append({"clips": [text_clip]})

    if music_url:
        audio_clip = {
            "asset": {"type": "audio", "src": music_url},
            "start": 0,
            "length": clip_length,
            "volume": 0.4,
            "effect": "fadeInFadeOut",
        }
        tracks.append({"clips": [audio_clip]})

    return {
        "timeline": {"background": "#000000", "tracks": tracks},
        "output": {"format": "mp4", "resolution": "sd", "fps": 25},
    }


def fetch_data(
    api_key: str,
    video_bytes: bytes,
    trim_start: float,
    trim_end: float,
    text_overlay: str = "",
    music_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Render a Shotstack edit and return final video URL details."""
    if not api_key or not api_key.strip():
        raise ValueError("A Shotstack Production API key is required")
    if not video_bytes:
        raise ValueError("A video file upload is required")

    source_id = _upload_video_source(api_key=api_key, video_bytes=video_bytes)

    payload = _build_timeline_payload(
        source_id=source_id,
        trim_start=trim_start,
        trim_end=trim_end,
        text_overlay=text_overlay,
        music_url=music_url,
    )

    render_response = _request(
        settings.SHOTSTACK_EDIT_BASE_URL,
        "POST",
        RENDER_ENDPOINT,
        api_key,
        json_payload=payload,
        timeout=settings.DEFAULT_TIMEOUT * 2,
    )

    render_id = _extract(render_response, "response.id", "data.id", "id")
    if not render_id:
        raise RuntimeError("Shotstack render ID was not returned")

    deadline = time.time() + settings.RENDER_WAIT_TIMEOUT
    while time.time() < deadline:
        status_response = _request(
            settings.SHOTSTACK_EDIT_BASE_URL,
            "GET",
            f"{RENDER_ENDPOINT}/{render_id}",
            api_key,
            timeout=settings.DEFAULT_TIMEOUT,
        )
        status = str(_extract(status_response, "response.status", "data.attributes.status", "data.status", "status") or "").lower()

        if status == "done":
            final_url = _render_output_url(status_response)
            if not final_url:
                raise RuntimeError("Render finished but no downloadable video URL was returned")
            return {"status": "done", "url": str(final_url), "render_id": str(render_id)}

        if status in {"failed", "error"}:
            message = _extract(
                status_response,
                "response.error",
                "response.message",
                "data.attributes.error",
                "message",
            ) or "Shotstack render failed"
            return {"status": "failed", "error": str(message), "render_id": str(render_id)}

        time.sleep(settings.POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"Timed out waiting for Shotstack render {render_id}")
