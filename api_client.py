from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from config import settings


INIT_UPLOAD_ENDPOINT = "/v1/files/init-upload"
COMPLETE_UPLOAD_ENDPOINT = "/v1/files/{file_id}/complete-upload"
FILE_STATUS_ENDPOINT = "/v1/files/{file_id}"
RUN_COMMAND_ENDPOINT = "/v1/run-ffmpeg-command"
COMMAND_STATUS_ENDPOINT = "/v1/commands/{command_id}"

DEFAULT_PART_SIZE = 10 * 1024 * 1024  # 10 MiB fallback if Rendi does not return one.


def _normalize_api_key(api_key: str) -> str:
    """Extract a Rendi key from common copied HTTP-header formats."""
    value = api_key.strip()
    for prefix in ("x-api-key:", "authorization:"):
        if value.lower().startswith(prefix):
            value = value[len(prefix) :].strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


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
    error = _extract(body, "error", "errors", "message")
    if isinstance(error, dict):
        parts = []
        name = error.get("name") or error.get("code")
        if name:
            parts.append(str(name))
        if error.get("message"):
            parts.append(str(error["message"]))
        if parts:
            return "; ".join(parts)
    elif isinstance(error, list):
        parts = [str(item.get("message", item)) if isinstance(item, dict) else str(item) for item in error]
        if parts:
            return "; ".join(parts)
    elif isinstance(error, str) and error:
        return error
    return None


def _request(
    method: str,
    path: str,
    api_key: str,
    *,
    json_payload: Optional[Dict[str, Any]] = None,
    timeout: Optional[int] = None,
) -> Any:
    base_url = settings.RENDI_API_BASE_URL
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"X-API-KEY": _normalize_api_key(api_key), "Accept": "application/json"}
    if json_payload is not None:
        headers["Content-Type"] = "application/json"

    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_payload,
            timeout=timeout or settings.DEFAULT_TIMEOUT,
        )
    except requests.exceptions.ConnectionError as exc:
        raise requests.exceptions.ConnectionError(
            f"Could not reach {base_url} ({method.upper()} {path}); check your network connection "
            "and that this environment allows outbound requests to the Rendi API host",
            response=getattr(exc, "response", None),
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise requests.exceptions.Timeout(
            f"Timed out connecting to {base_url} ({method.upper()} {path}); the Rendi API host "
            "may be unreachable from this environment",
            response=getattr(exc, "response", None),
        ) from exc

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
        if response.status_code == 401:
            mismatch_hint = "Confirm your Rendi API key is valid and active"
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


def _upload_video_source(api_key: str, video_bytes: bytes, filename: str) -> str:
    """Upload a video to Rendi storage using the direct multipart upload flow."""
    init_response = _request(
        "POST",
        INIT_UPLOAD_ENDPOINT,
        api_key,
        json_payload={"filename": filename, "size_bytes": len(video_bytes)},
        timeout=settings.DEFAULT_TIMEOUT,
    )

    file_id = _extract(init_response, "file_id")
    upload_urls = _extract(init_response, "upload_urls") or []
    part_size = int(_extract(init_response, "part_size") or DEFAULT_PART_SIZE)

    if not file_id or not upload_urls:
        raise RuntimeError("Could not retrieve Rendi upload URLs or file ID")

    parts: List[Dict[str, Any]] = []
    for index, upload_url in enumerate(upload_urls, start=1):
        chunk = video_bytes[(index - 1) * part_size : index * part_size]
        put_response = requests.put(
            upload_url,
            data=chunk,
            timeout=settings.UPLOAD_TIMEOUT,
        )
        put_response.raise_for_status()
        etag = put_response.headers.get("ETag", "").strip('"')
        parts.append({"part_number": index, "etag": etag})

    complete_response = _request(
        "POST",
        COMPLETE_UPLOAD_ENDPOINT.format(file_id=file_id),
        api_key,
        json_payload={"parts": parts},
        timeout=settings.UPLOAD_TIMEOUT,
    )

    status = str(_extract(complete_response, "status") or "").upper()
    storage_url = _extract(complete_response, "storage_url")

    # Wait for Rendi to finish analyzing (ffprobe) the uploaded file.
    deadline = time.time() + settings.UPLOAD_WAIT_TIMEOUT
    while status not in {"STORED"} and time.time() < deadline:
        if status in {"FAILED", "ERROR"}:
            message = _extract(complete_response, "error", "message") or "File upload failed"
            raise RuntimeError(str(message))
        time.sleep(settings.POLL_INTERVAL_SECONDS)
        file_response = _request(
            "GET",
            FILE_STATUS_ENDPOINT.format(file_id=file_id),
            api_key,
            timeout=settings.DEFAULT_TIMEOUT,
        )
        status = str(_extract(file_response, "status") or "").upper()
        storage_url = _extract(file_response, "storage_url") or storage_url
        complete_response = file_response

    if not storage_url:
        raise TimeoutError("Timed out waiting for uploaded file to become ready on Rendi")

    return str(storage_url)


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


def _build_ffmpeg_payload(
    video_url: str,
    trim_start: float,
    trim_end: float,
    text_overlay: str,
    music_url: Optional[str],
) -> Dict[str, Any]:
    if trim_end <= trim_start:
        raise ValueError("Trim end must be greater than trim start")

    clip_length = round(trim_end - trim_start, 3)

    input_files = {"in_1": video_url}

    video_chain = f"[0:v]trim=start={trim_start}:end={trim_end},setpts=PTS-STARTPTS"
    if text_overlay:
        escaped_text = _escape_drawtext(text_overlay)
        video_chain += (
            f",drawtext=text='{escaped_text}':fontcolor=white:fontsize=24"
            ":x=(w-text_w)/2:y=h-text_h-40:enable='lte(t,5)'"
        )
    video_chain += "[vout]"

    filter_parts = [video_chain, f"[0:a]atrim=start={trim_start}:end={trim_end},asetpts=PTS-STARTPTS[a0]"]
    map_args = ["-map", "[vout]"]

    if music_url:
        input_files["in_2"] = music_url
        fade_out_start = max(clip_length - 1, 0)
        filter_parts.append(
            f"[1:a]atrim=start=0:end={clip_length},asetpts=PTS-STARTPTS,volume=0.4,"
            f"afade=t=in:d=1,afade=t=out:st={fade_out_start}:d=1[a1]"
        )
        filter_parts.append("[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]")
        map_args += ["-map", "[aout]"]
    else:
        map_args += ["-map", "[a0]"]

    filter_complex = ";".join(filter_parts)
    inputs_cmd = " ".join(f"-i {{{{in_{i}}}}}" for i in range(1, len(input_files) + 1))
    command = f'{inputs_cmd} -filter_complex "{filter_complex}" {" ".join(map_args)} {{{{out_1}}}}'

    return {
        "input_files": input_files,
        "output_files": {"out_1": "output.mp4"},
        "ffmpeg_command": command,
    }


def fetch_data(
    api_key: str,
    video_bytes: bytes,
    trim_start: float,
    trim_end: float,
    text_overlay: str = "",
    music_url: Optional[str] = None,
    filename: str = "input.mp4",
) -> Dict[str, Any]:
    """Render a video via the Rendi FFmpeg API and return the final video URL details."""
    if not api_key or not _normalize_api_key(api_key):
        raise ValueError("A Rendi API key is required")
    if not video_bytes:
        raise ValueError("A video file upload is required")

    video_url = _upload_video_source(api_key=api_key, video_bytes=video_bytes, filename=filename)

    payload = _build_ffmpeg_payload(
        video_url=video_url,
        trim_start=trim_start,
        trim_end=trim_end,
        text_overlay=text_overlay,
        music_url=music_url,
    )

    submit_response = _request(
        "POST",
        RUN_COMMAND_ENDPOINT,
        api_key,
        json_payload=payload,
        timeout=settings.DEFAULT_TIMEOUT * 2,
    )

    command_id = _extract(submit_response, "command_id")
    if not command_id:
        raise RuntimeError("Rendi command ID was not returned")

    deadline = time.time() + settings.COMMAND_WAIT_TIMEOUT
    while time.time() < deadline:
        status_response = _request(
            "GET",
            COMMAND_STATUS_ENDPOINT.format(command_id=command_id),
            api_key,
            timeout=settings.DEFAULT_TIMEOUT,
        )
        status = str(_extract(status_response, "status") or "").upper()

        if status == "SUCCESS":
            final_url = _extract(status_response, "output_files.out_1.storage_url")
            if not final_url:
                raise RuntimeError("Render finished but no downloadable video URL was returned")
            return {"status": "done", "url": str(final_url), "command_id": str(command_id)}

        if status in {"FAILED", "ERROR"}:
            message = _extract(status_response, "error", "message") or "Rendi render failed"
            return {"status": "failed", "error": str(message), "command_id": str(command_id)}

        time.sleep(settings.POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"Timed out waiting for Rendi command {command_id}")
