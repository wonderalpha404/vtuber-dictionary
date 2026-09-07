#!/usr/bin/env python3
"""Research script for a single VTuber using OpenRouter API with web search.

Accepts a UUID as the sole positional argument.

Uses source/vdb.json (read-only) to find the VTuber entry and its name.jp.

On successful research, writes/updates source/vtuber-readings.json.

On technical failure, writes only a minimal failure-state record to
source/vtuber-readings.json and exits with a non-zero status.

Detailed errors, API responses, stderr information, and exception details are
never stored in vtuber-readings.json. They are emitted only to stderr so they
are visible in GitHub Actions logs.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openrouter/free"

# Maximum number of API attempts for transient failures.
MAX_API_ATTEMPTS = 3

# Requests timeout:
# - connect timeout: 15 seconds
# - read timeout: 60 seconds
#
# This is intentionally not an extremely short timeout because Web Search
# may take some time.
REQUEST_TIMEOUT = (15, 60)

# Maximum amount of AI response content shown in Actions logs when parsing
# fails. Never print the complete response.
RESPONSE_PREVIEW_LIMIT = 500


def utc_now() -> str:
    """Return current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    """Write a diagnostic message to stderr."""
    print(message, file=sys.stderr)


def load_json_file(file_path: str) -> Any:
    """Load JSON file with error handling."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    except FileNotFoundError:
        log(f"ERROR: JSON file not found: {file_path}")
        sys.exit(1)

    except json.JSONDecodeError as e:
        log(
            f"ERROR: Invalid JSON in {file_path}: "
            f"line={e.lineno} column={e.colno} message={e.msg}"
        )
        sys.exit(1)


def find_vdb_entry_by_uuid(
    vdb_data: dict,
    uuid: str,
) -> Optional[dict]:
    """Find VTuber entry in VDB by UUID."""
    vtbs = vdb_data.get("vtbs", [])

    if not isinstance(vtbs, list):
        log("ERROR: VDB 'vtbs' field is not an array.")
        sys.exit(1)

    for vtuber in vtbs:
        if isinstance(vtuber, dict) and vtuber.get("uuid") == uuid:
            return vtuber

    return None


def build_auxiliary_info(vdb_entry: Optional[dict]) -> str:
    """Build auxiliary information from VDB entry."""
    if not vdb_entry:
        return ""

    aux_lines = []
    name_obj = vdb_entry.get("name", {})

    if not isinstance(name_obj, dict):
        return ""

    for key in ["jp", "cn", "en", "default", "extra"]:
        if key not in name_obj:
            continue

        value = name_obj[key]

        if isinstance(value, list):
            aux_lines.append(
                f"  {key}: {', '.join(str(v) for v in value)}"
            )
        else:
            aux_lines.append(f"  {key}: {value}")

    return "\n".join(aux_lines) if aux_lines else ""


def build_research_prompt(
    name_jp: str,
    uuid: str,
    entry: dict,
    aux_info: str,
) -> str:
    """Build a strict, bounded research prompt for the AI."""

    return f"""You are researching the actual Japanese reading/pronunciation of a specific VTuber's name.

TARGET VTUBER:
- Japanese name: {name_jp}
- UUID: {uuid}

Auxiliary VDB information:
{aux_info if aux_info else "  No auxiliary information available"}

Your task is ONLY to determine the actual reading of this exact VTuber's Japanese name.

RESEARCH ORDER
==============

STEP 1 — Official sources
Search official sources first, including:
- official website
- official profile
- official X/Twitter profile
- official YouTube/channel profile
- official agency/talent profile
- official event/profile pages

If an official source clearly establishes the reading, use it and stop searching.

STEP 2 — Reliable third-party sources
If official sources do not establish the reading, check a small number of reliable third-party sources, prioritizing:
- Japanese Wikipedia
- established VTuber databases
- established Japanese media/reference sites
- reliable profile/database pages that clearly identify this exact VTuber

Wikipedia is acceptable as a trustworthy third-party source.
If Wikipedia is the only reliable evidence, normally use confidence "medium", not "high".

If reliable third-party sources clearly agree on the reading, stop searching.

STEP 3 — Limited additional search
Only if the reading is still unresolved, perform a limited search for the exact VTuber name.

Do NOT:
- search indefinitely
- repeatedly search the same query
- investigate unrelated biography
- search broadly for unrelated people with similar names

If reliable evidence is still unavailable after the limited search, return:
- reading = ""
- confidence = "unknown"
- status = "unknown"

STRICT EVIDENCE RULES
=====================

1. Never guess the reading.
2. Never infer a reading merely from normal Japanese kanji pronunciation.
3. Never say "this name is usually read..." without actual evidence.
4. Never use information from a different person, character, company, group, or VTuber.
5. The evidence must identify this exact VTuber.
6. Do not rely solely on search-result snippets.
7. When possible, verify the actual source page.
8. Do not fabricate URLs.
9. Only include URLs that were actually used as evidence.
10. If sources conflict, use status "review".
11. If reliable evidence establishes the reading without meaningful conflict, use "verified".
12. If reliable evidence exists only from weaker third-party sources, use "review" or "medium" as appropriate.
13. If no reliable evidence exists, use "unknown".
14. Once sufficient evidence is found, STOP SEARCHING.

CONFIDENCE RULES
================

- high:
  Clear official source, or exceptionally strong corroborated evidence.
- medium:
  Reliable third-party evidence, including Wikipedia or established databases.
- review:
  Conflicting or materially uncertain evidence.
- unknown:
  No reliable evidence establishing the reading.

STATUS RULES
============

- verified:
  Reliable evidence establishes the reading and there is no meaningful conflict.
- review:
  Evidence exists but there is uncertainty or conflict.
- unknown:
  No reliable evidence establishes the reading.

Never use "verified" or "review" with an empty reading.

OUTPUT REQUIREMENTS
===================

You MUST return exactly one JSON object.

The response MUST:
- contain only JSON
- contain no Markdown
- contain no ```json code fence
- contain no explanation before or after the JSON
- contain exactly these seven keys:

{{
  "name": "{name_jp}",
  "reading": "",
  "source": "",
  "source_type": "",
  "confidence": "high",
  "status": "verified",
  "notes": ""
}}

The values must follow these rules:

name:
- Must exactly equal the target Japanese name: {name_jp}

reading:
- Actual Japanese reading only.
- Empty string if reliable evidence was not found.

source:
- URL or concise list of URLs actually used as evidence.
- Empty only when confidence is unknown.

source_type:
- Describe the evidence type briefly, for example:
  "official"
  "official_profile"
  "wikipedia"
  "database"
  "official_and_database"

confidence:
- Exactly one of:
  "high"
  "medium"
  "review"
  "unknown"

status:
- Exactly one of:
  "verified"
  "review"
  "unknown"

notes:
- Concise explanation of the evidence and conclusion.
- Do not include unrelated biography.
- Do not fabricate evidence.

IMPORTANT:
Do not return Markdown.
Do not return commentary.
Do not return multiple JSON objects.
Do not return a JSON array.
Return one valid JSON object only.
"""


def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code."""
    if status_code == 429:
        return "http_429_rate_limited"

    if 400 <= status_code <= 499:
        return f"http_{status_code}_client_error"

    if status_code == 500:
        return "http_500_server_error"

    if status_code == 502:
        return "http_502_bad_gateway"

    if status_code == 503:
        return "http_503_service_unavailable"

    if status_code == 504:
        return "http_504_gateway_timeout"

    if 500 <= status_code <= 599:
        return f"http_{status_code}_server_error"

    return f"http_{status_code}"


def is_retryable_http_status(status_code: int) -> bool:
    """Return whether an HTTP status should be retried."""
    return status_code == 429 or status_code in {
        500,
        502,
        503,
        504,
    }


def preview_text(text: str, limit: int = RESPONSE_PREVIEW_LIMIT) -> str:
    """Return a safe, short preview for diagnostics."""
    if not text:
        return "<empty>"

    normalized = text.replace("\r", "\\r").replace("\n", "\\n")

    if len(normalized) <= limit:
        return normalized

    return normalized[:limit] + "...[truncated]"


def response_preview_start(
    text: str,
    limit: int = RESPONSE_PREVIEW_LIMIT,
) -> str:
    """Return beginning of response for diagnostics."""
    return preview_text(text[:limit], limit)


def response_preview_end(
    text: str,
    limit: int = RESPONSE_PREVIEW_LIMIT,
) -> str:
    """Return end of response for diagnostics."""
    if not text:
        return "<empty>"

    return preview_text(text[-limit:], limit)


def extract_message_content(message: dict) -> str:
    """Extract assistant message content safely."""
    content = message.get("content")

    if isinstance(content, str):
        return content

    # Some APIs/models may return structured content.
    # We do not blindly convert arbitrary structures to JSON as the answer.
    # Instead, explicitly support simple text-part arrays.
    if isinstance(content, list):
        text_parts = []

        for part in content:
            if not isinstance(part, dict):
                continue

            text = part.get("text")

            if isinstance(text, str):
                text_parts.append(text)

        if text_parts:
            return "".join(text_parts)

    raise ValueError(
        f"assistant message content has unsupported type: "
        f"{type(content).__name__}"
    )


def call_openrouter_api(
    prompt: str,
    name_jp: str,
    uuid: str,
) -> str:
    """Call OpenRouter API with bounded retries and detailed diagnostics."""

    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        log(
            f"OPENROUTER ERROR: name={name_jp} uuid={uuid} "
            "error_type=missing_api_key"
        )
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/wonderalpha404/vtuber-dictionary",
        "X-Title": "VTuber Dictionary",
    }

    tools = [
        {
            "type": "openrouter:web_search",
        }
    ]

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "tools": tools,
        # Ask the provider/model for JSON output when supported.
        # Response parsing below still handles models that return fenced JSON.
        "response_format": {
            "type": "json_object",
        },
    }

    log("")
    log("OPENROUTER REQUEST")
    log(f"name={name_jp}")
    log(f"uuid={uuid}")
    log(f"model={OPENROUTER_MODEL}")
    log("web_search=true")
    log(
        f"connect_timeout={REQUEST_TIMEOUT[0]}s "
        f"read_timeout={REQUEST_TIMEOUT[1]}s"
    )
    log(f"max_attempts={MAX_API_ATTEMPTS}")

    last_exception: Optional[Exception] = None

    for attempt in range(1, MAX_API_ATTEMPTS + 1):
        log("")
        log(
            f"OPENROUTER ATTEMPT {attempt}/{MAX_API_ATTEMPTS} "
            f"name={name_jp} uuid={uuid}"
        )

        try:
            started = time.monotonic()

            response = requests.post(
                OPENROUTER_URL,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )

            elapsed = time.monotonic() - started

            log(
                f"OPENROUTER HTTP RESPONSE "
                f"name={name_jp} uuid={uuid} "
                f"status={response.status_code} "
                f"elapsed={elapsed:.1f}s "
                f"bytes={len(response.content)}"
            )

            if response.status_code >= 400:
                error_type = classify_http_error(
                    response.status_code
                )

                log(
                    f"OPENROUTER HTTP ERROR "
                    f"name={name_jp} uuid={uuid} "
                    f"error_type={error_type}"
                )

                # Log a short provider error preview.
                log(
                    "HTTP ERROR BODY PREVIEW: "
                    f"{response_preview_start(response.text)}"
                )

                if (
                    is_retryable_http_status(response.status_code)
                    and attempt < MAX_API_ATTEMPTS
                ):
                    wait_seconds = 2 ** (attempt - 1)

                    log(
                        f"OPENROUTER RETRYING "
                        f"name={name_jp} uuid={uuid} "
                        f"wait={wait_seconds}s"
                    )

                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()

            if not response.content:
                error = RuntimeError("empty HTTP response body")

                log(
                    f"OPENROUTER ERROR "
                    f"name={name_jp} uuid={uuid} "
                    "error_type=empty_http_response"
                )

                last_exception = error

                if attempt < MAX_API_ATTEMPTS:
                    wait_seconds = 2 ** (attempt - 1)
                    log(
                        f"OPENROUTER RETRYING "
                        f"name={name_jp} uuid={uuid} "
                        f"wait={wait_seconds}s"
                    )
                    time.sleep(wait_seconds)
                    continue

                raise error

            try:
                response_data = response.json()

            except json.JSONDecodeError as e:
                log(
                    f"OPENROUTER ERROR "
                    f"name={name_jp} uuid={uuid} "
                    "error_type=invalid_api_response_json "
                    f"line={e.lineno} column={e.colno}"
                )

                log(
                    "API RESPONSE PREVIEW: "
                    f"{response_preview_start(response.text)}"
                )

                raise ValueError(
                    "OpenRouter HTTP response was not valid JSON"
                ) from e

            if not isinstance(response_data, dict):
                log(
                    f"OPENROUTER ERROR "
                    f"name={name_jp} uuid={uuid} "
                    "error_type=api_response_not_object"
                )
                raise ValueError(
                    "OpenRouter API response is not a JSON object"
                )

            log(
                "OPENROUTER RESPONSE STRUCTURE "
                f"name={name_jp} uuid={uuid} "
                f"top_level_keys={sorted(response_data.keys())}"
            )

            if "error" in response_data:
                error_obj = response_data.get("error")

                log(
                    f"OPENROUTER API ERROR OBJECT "
                    f"name={name_jp} uuid={uuid} "
                    f"error_type=api_error"
                )

                if isinstance(error_obj, dict):
                    log(
                        f"API error code={error_obj.get('code')} "
                        f"type={error_obj.get('type')} "
                        f"message={preview_text(str(error_obj.get('message', '')))}"
                    )

                raise RuntimeError("OpenRouter returned an API error object")

            if "choices" not in response_data:
                log(
                    f"OPENROUTER ERROR "
                    f"name={name_jp} uuid={uuid} "
                    "error_type=missing_choices"
                )
                raise ValueError("'choices' field not found")

            choices = response_data.get("choices")

            if not isinstance(choices, list):
                log(
                    f"OPENROUTER ERROR "
                    f"name={name_jp} uuid={uuid} "
                    "error_type=choices_not_array"
                )
                raise ValueError("'choices' is not an array")

            log(
                f"OPENROUTER CHOICES "
                f"name={name_jp} uuid={uuid} "
                f"count={len(choices)}"
            )

            if not choices:
                log(
                    f"OPENROUTER ERROR "
                    f"name={name_jp} uuid={uuid} "
                    "error_type=empty_choices"
                )
                raise ValueError("empty choices array")

            first_choice = choices[0]

            if not isinstance(first_choice, dict):
                log(
                    f"OPENROUTER ERROR "
                    f"name={name_jp} uuid={uuid} "
                    "error_type=invalid_first_choice"
                )
                raise ValueError("first choice is not an object")

            message = first_choice.get("message")

            if not isinstance(message, dict):
                log(
                    f"OPENROUTER ERROR "
                    f"name={name_jp} uuid={uuid} "
                    "error_type=missing_message"
                )
                raise ValueError("message is missing or invalid")

            log(
                "OPENROUTER MESSAGE FOUND "
                f"name={name_jp} uuid={uuid} "
                f"message_keys={sorted(message.keys())}"
            )

            content = extract_message_content(message)

            if not content.strip():
                log(
                    f"OPENROUTER ERROR "
                    f"name={name_jp} uuid={uuid} "
                    "error_type=empty_ai_content"
                )
                raise ValueError("assistant message content is empty")

            log(
                "OPENROUTER AI CONTENT RECEIVED "
                f"name={name_jp} uuid={uuid} "
                f"content_length={len(content)}"
            )

            return content

        except requests.exceptions.Timeout as e:
            last_exception = e

            log(
                f"OPENROUTER ERROR "
                f"name={name_jp} uuid={uuid} "
                "error_type=timeout "
                f"attempt={attempt}/{MAX_API_ATTEMPTS}"
            )

            if attempt < MAX_API_ATTEMPTS:
                wait_seconds = 2 ** (attempt - 1)
                log(
                    f"OPENROUTER RETRYING "
                    f"name={name_jp} uuid={uuid} "
                    f"wait={wait_seconds}s"
                )
                time.sleep(wait_seconds)
                continue

            raise RuntimeError(
                "OpenRouter request timed out after all attempts"
            ) from e

        except requests.exceptions.ConnectionError as e:
            last_exception = e

            log(
                f"OPENROUTER ERROR "
                f"name={name_jp} uuid={uuid} "
                "error_type=connection_error "
                f"attempt={attempt}/{MAX_API_ATTEMPTS}"
            )

            if attempt < MAX_API_ATTEMPTS:
                wait_seconds = 2 ** (attempt - 1)
                log(
                    f"OPENROUTER RETRYING "
                    f"name={name_jp} uuid={uuid} "
                    f"wait={wait_seconds}s"
                )
                time.sleep(wait_seconds)
                continue

            raise RuntimeError(
                "OpenRouter connection failed after all attempts"
            ) from e

        except requests.exceptions.HTTPError as e:
            last_exception = e

            status_code = (
                e.response.status_code
                if e.response is not None
                else None
            )

            log(
                f"OPENROUTER ERROR "
                f"name={name_jp} uuid={uuid} "
                "error_type=http_error "
                f"status={status_code}"
            )

            raise

        except requests.exceptions.RequestException as e:
            last_exception = e

            log(
                f"OPENROUTER ERROR "
                f"name={name_jp} uuid={uuid} "
                f"error_type=request_exception "
                f"message={preview_text(str(e))}"
            )

            raise

        except Exception as e:
            last_exception = e

            log(
                f"OPENROUTER PROCESSING ERROR "
                f"name={name_jp} uuid={uuid} "
                f"error_type={type(e).__name__} "
                f"message={preview_text(str(e))}"
            )

            raise

    if last_exception is not None:
        raise RuntimeError(
            "OpenRouter request failed after all attempts"
        ) from last_exception

    raise RuntimeError("OpenRouter request failed")


def strip_markdown_json_fence(content: str) -> str:
    """Remove a Markdown JSON code fence if one was returned."""
    text = content.strip()

    if not text.startswith("```"):
        return text

    lines = text.splitlines()

    if not lines:
        return text

    # Remove opening fence such as ``` or ```json.
    first_line = lines[0].strip()

    if not first_line.startswith("```"):
        return text

    lines = lines[1:]

    # Remove closing fence if present.
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    return "\n".join(lines).strip()


def try_extract_json_object(content: str) -> Optional[str]:
    """
    Attempt to extract one JSON object from surrounding text.

    This is a fallback only.

    We do NOT attempt arbitrary correction or fabrication of JSON.
    """
    text = content.strip()

    if not text:
        return None

    # First try the entire content.
    try:
        parsed = json.loads(text)

        if isinstance(parsed, dict):
            return text

    except json.JSONDecodeError:
        pass

    # Then handle Markdown fence.
    unfenced = strip_markdown_json_fence(text)

    if unfenced != text:
        try:
            parsed = json.loads(unfenced)

            if isinstance(parsed, dict):
                return unfenced

        except json.JSONDecodeError:
            pass

    # Last safe fallback:
    # locate the first { and last } and try that exact substring.
    #
    # We do not modify its contents.
    first_brace = text.find("{")
    last_brace = text.rfind("}")

    if first_brace >= 0 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]

        try:
            parsed = json.loads(candidate)

            if isinstance(parsed, dict):
                return candidate

        except json.JSONDecodeError:
            pass

    return None


def parse_ai_response(
    content: str,
    expected_name: str,
) -> dict:
    """Parse and strictly validate AI response JSON."""

    raw_content = content.strip()

    if not raw_content:
        log(
            f"AI RESPONSE PARSE FAILED "
            f"name={expected_name} error_type=empty_content"
        )
        raise ValueError("AI response content is empty")

    log(
        f"AI RESPONSE RECEIVED "
        f"name={expected_name} "
        f"content_length={len(raw_content)}"
    )

    json_text = try_extract_json_object(raw_content)

    if json_text is None:
        log(
            f"AI RESPONSE PARSE FAILED "
            f"name={expected_name} "
            "error_type=invalid_json"
        )

        log(
            f"AI RESPONSE START PREVIEW: "
            f"{response_preview_start(raw_content)}"
        )

        log(
            f"AI RESPONSE END PREVIEW: "
            f"{response_preview_end(raw_content)}"
        )

        raise ValueError(
            "Failed to parse AI response as a JSON object"
        )

    try:
        result = json.loads(json_text)

    except json.JSONDecodeError as e:
        log(
            f"AI RESPONSE PARSE FAILED "
            f"name={expected_name} "
            "error_type=json_decode_error "
            f"line={e.lineno} "
            f"column={e.colno} "
            f"message={e.msg}"
        )

        log(
            f"AI RESPONSE START PREVIEW: "
            f"{response_preview_start(raw_content)}"
        )

        log(
            f"AI RESPONSE END PREVIEW: "
            f"{response_preview_end(raw_content)}"
        )

        raise

    if not isinstance(result, dict):
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=not_object"
        )
        raise ValueError("AI response is not a JSON object")

    required_keys = [
        "name",
        "reading",
        "source",
        "source_type",
        "confidence",
        "status",
        "notes",
    ]

    missing_keys = [
        key for key in required_keys
        if key not in result
    ]

    if missing_keys:
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=missing_keys "
            f"keys={missing_keys}"
        )
        raise ValueError(
            f"Missing required keys: {', '.join(missing_keys)}"
        )

    if result["name"] != expected_name:
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=name_mismatch "
            f"returned_name={result['name']!r}"
        )
        raise ValueError("AI response name mismatch")

    valid_confidences = {
        "high",
        "medium",
        "review",
        "unknown",
    }

    if result["confidence"] not in valid_confidences:
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=invalid_confidence "
            f"value={result['confidence']!r}"
        )
        raise ValueError("Invalid confidence")

    valid_statuses = {
        "verified",
        "review",
        "unknown",
    }

    if result["status"] not in valid_statuses:
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=invalid_status "
            f"value={result['status']!r}"
        )
        raise ValueError("Invalid status")

    if not isinstance(result["reading"], str):
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=reading_not_string"
        )
        raise ValueError("reading must be a string")

    if not isinstance(result["source"], str):
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=source_not_string"
        )
        raise ValueError("source must be a string")

    if not isinstance(result["source_type"], str):
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=source_type_not_string"
        )
        raise ValueError("source_type must be a string")

    if not isinstance(result["notes"], str):
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=notes_not_string"
        )
        raise ValueError("notes must be a string")

    reading = result["reading"].strip()
    source = result["source"].strip()

    if result["status"] in {"verified", "review"}:
        if not reading:
            log(
                f"AI RESPONSE VALIDATION ERROR "
                f"name={expected_name} "
                "error_type=empty_reading_for_non_unknown_status "
                f"status={result['status']}"
            )
            raise ValueError(
                "verified/review requires a non-empty reading"
            )

    if result["confidence"] in {
        "high",
        "medium",
        "review",
    } and not source:
        log(
            f"AI RESPONSE VALIDATION ERROR "
            f"name={expected_name} "
            "error_type=missing_source_for_confidence "
            f"confidence={result['confidence']}"
        )
        raise ValueError(
            "Non-unknown confidence requires a source"
        )

    if result["status"] == "unknown":
        if reading:
            log(
                f"AI RESPONSE VALIDATION ERROR "
                f"name={expected_name} "
                "error_type=unknown_with_nonempty_reading"
            )
            raise ValueError(
                "unknown status must have an empty reading"
            )

    if result["status"] == "verified":
        if result["confidence"] == "unknown":
            log(
                f"AI RESPONSE VALIDATION ERROR "
                f"name={expected_name} "
                "error_type=verified_with_unknown_confidence"
            )
            raise ValueError(
                "verified cannot use unknown confidence"
            )

    if result["status"] == "review":
        if result["confidence"] == "unknown":
            log(
                f"AI RESPONSE VALIDATION ERROR "
                f"name={expected_name} "
                "error_type=review_with_unknown_confidence"
            )
            raise ValueError(
                "review cannot use unknown confidence"
            )

    log(
        f"AI RESPONSE PARSED "
        f"name={expected_name} "
        f"status={result['status']} "
        f"confidence={result['confidence']} "
        f"reading_present={bool(reading)} "
        f"source_present={bool(source)}"
    )

    return result


def readings_path() -> Path:
    """Return path to vtuber-readings.json."""
    return (
        Path(__file__).resolve().parent.parent
        / "source"
        / "vtuber-readings.json"
    )


def load_readings() -> list:
    """Load the current readings result file."""
    path = readings_path()

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

    except FileNotFoundError:
        return []

    except json.JSONDecodeError as e:
        log(
            f"ERROR: Invalid JSON in {path}: "
            f"line={e.lineno} column={e.colno} message={e.msg}"
        )
        raise

    if not isinstance(data, list):
        raise ValueError(
            f"{path} must contain a JSON array"
        )

    return data


def write_readings(new_list: list) -> None:
    """Write the complete readings result file."""
    path = readings_path()

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            new_list,
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")


def save_result(
    uuid: str,
    name_jp: str,
    ai_result: dict,
) -> bool:
    """
    Save or update a successful research result.

    Existing verified/review/unknown records are protected.

    Returns:
        True  = new result written
        False = existing successful result protected
    """
    now = utc_now()

    record = {
        "uuid": uuid,
        "name": name_jp,
        "reading": ai_result["reading"].strip(),
        "source": ai_result["source"].strip(),
        "source_type": ai_result["source_type"].strip(),
        "confidence": ai_result["confidence"],
        "status": ai_result["status"],
        "notes": ai_result.get("notes", "").strip(),
        "checked_at": now,
    }

    readings = load_readings()

    protected_statuses = {
        "verified",
        "review",
        "unknown",
    }

    for i, existing in enumerate(readings):
        if existing.get("uuid") != uuid:
            continue

        if existing.get("status") in protected_statuses:
            log(
                f"RESULT SAVE SKIPPED "
                f"name={name_jp} uuid={uuid} "
                f"reason=existing_successful_status "
                f"status={existing.get('status')}"
            )
            return False

        readings[i] = record
        write_readings(readings)

        log(
            f"RESULT SAVED "
            f"name={name_jp} uuid={uuid} "
            f"status={record['status']} "
            f"confidence={record['confidence']}"
        )

        return True

    readings.append(record)
    write_readings(readings)

    log(
        f"RESULT SAVED "
        f"name={name_jp} uuid={uuid} "
        f"status={record['status']} "
        f"confidence={record['confidence']}"
    )

    return True


def save_failure_state(
    uuid: str,
    name_jp: str,
) -> None:
    """
    Save only the minimal technical failure state.

    Never store detailed exception information, stderr, AI response,
    HTTP response, or API credentials in the result file.
    """
    now = utc_now()

    fail_record = {
        "uuid": uuid,
        "name": name_jp,
        "reading": "",
        "source": "",
        "source_type": "",
        "confidence": "unknown",
        "status": "pending",
        "notes": "",
        "checked_at": "",
        "last_attempted_at": now,
        "last_attempt_result": "error",
    }

    readings = load_readings()

    protected_statuses = {
        "verified",
        "review",
        "unknown",
    }

    for i, existing in enumerate(readings):
        if existing.get("uuid") != uuid:
            continue

        if existing.get("status") in protected_statuses:
            log(
                f"FAILURE STATE NOT SAVED OVER SUCCESS "
                f"name={name_jp} uuid={uuid} "
                f"existing_status={existing.get('status')}"
            )
            return

        readings[i] = fail_record
        write_readings(readings)

        log(
            f"FAILURE STATE SAVED "
            f"name={name_jp} uuid={uuid} "
            "status=pending last_attempt_result=error"
        )
        return

    readings.append(fail_record)
    write_readings(readings)

    log(
        f"FAILURE STATE SAVED "
        f"name={name_jp} uuid={uuid} "
        "status=pending last_attempt_result=error"
    )


def fail_with_state(
    uuid: str,
    name_jp: str,
    error_type: str,
    exception: Optional[Exception] = None,
) -> None:
    """Log a technical failure, save minimal state, and exit."""
    if exception is not None:
        log(
            f"RESEARCH FAILED "
            f"name={name_jp} uuid={uuid} "
            f"error_type={error_type} "
            f"exception_type={type(exception).__name__} "
            f"message={preview_text(str(exception))}"
        )
    else:
        log(
            f"RESEARCH FAILED "
            f"name={name_jp} uuid={uuid} "
            f"error_type={error_type}"
        )

    try:
        save_failure_state(
            uuid,
            name_jp,
        )
    except Exception as save_error:
        log(
            f"FAILURE STATE SAVE ERROR "
            f"name={name_jp} uuid={uuid} "
            f"error_type={type(save_error).__name__} "
            f"message={preview_text(str(save_error))}"
        )

    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        log(
            "ERROR: UUID must be provided as a command-line argument"
        )
        sys.exit(1)

    uuid = sys.argv[1]

    script_dir = Path(__file__).resolve().parent.parent
    vdb_file = script_dir / "source" / "vdb.json"

    log("")
    log("RESEARCH START")
    log(f"uuid={uuid}")

    # ------------------------------------------------------------
    # Load VDB
    # ------------------------------------------------------------
    try:
        vdb_data = load_json_file(str(vdb_file))

    except SystemExit:
        raise

    except Exception as e:
        log(
            f"RESEARCH FAILED "
            f"uuid={uuid} "
            "error_type=vdb_load_error"
        )
        sys.exit(1)

    entry = find_vdb_entry_by_uuid(
        vdb_data,
        uuid,
    )

    if not entry:
        log(
            f"RESEARCH FAILED "
            f"uuid={uuid} "
            "error_type=uuid_not_found_in_vdb"
        )
        sys.exit(1)

    # ------------------------------------------------------------
    # Extract name.jp
    # ------------------------------------------------------------
    name_obj = entry.get("name", {})

    if not isinstance(name_obj, dict):
        log(
            f"RESEARCH FAILED "
            f"uuid={uuid} "
            "error_type=invalid_name_object"
        )
        sys.exit(1)

    name_jp = name_obj.get("jp")

    if not isinstance(name_jp, str) or not name_jp.strip():
        log(
            f"RESEARCH FAILED "
            f"uuid={uuid} "
            "error_type=name_jp_missing_or_empty"
        )
        sys.exit(1)

    name_jp = name_jp.strip()

    log(
        f"RESEARCH TARGET "
        f"name={name_jp} uuid={uuid}"
    )

    # ------------------------------------------------------------
    # Build research prompt
    # ------------------------------------------------------------
    aux_info = build_auxiliary_info(entry)

    prompt = build_research_prompt(
        name_jp,
        uuid,
        entry,
        aux_info,
    )

    log(
        f"RESEARCH PROMPT READY "
        f"name={name_jp} uuid={uuid} "
        f"prompt_length={len(prompt)}"
    )

    # ------------------------------------------------------------
    # OpenRouter
    # ------------------------------------------------------------
    try:
        ai_response = call_openrouter_api(
            prompt,
            name_jp,
            uuid,
        )

    except requests.exceptions.Timeout as e:
        fail_with_state(
            uuid,
            name_jp,
            "openrouter_timeout",
            e,
        )

    except requests.exceptions.ConnectionError as e:
        fail_with_state(
            uuid,
            name_jp,
            "openrouter_connection_error",
            e,
        )

    except requests.exceptions.HTTPError as e:
        status_code = (
            e.response.status_code
            if e.response is not None
            else None
        )

        fail_with_state(
            uuid,
            name_jp,
            f"openrouter_http_error_{status_code}",
            e,
        )

    except Exception as e:
        fail_with_state(
            uuid,
            name_jp,
            "openrouter_or_api_error",
            e,
        )

    # ------------------------------------------------------------
    # Parse and validate AI response
    # ------------------------------------------------------------
    try:
        result = parse_ai_response(
            ai_response,
            name_jp,
        )

    except json.JSONDecodeError as e:
        fail_with_state(
            uuid,
            name_jp,
            "ai_json_decode_error",
            e,
        )

    except Exception as e:
        fail_with_state(
            uuid,
            name_jp,
            "ai_response_validation_error",
            e,
        )

    # ------------------------------------------------------------
    # Research outcome
    # ------------------------------------------------------------
    status = result["status"]
    reading = result["reading"].strip()
    confidence = result["confidence"]

    if status == "unknown":
        log("")
        log(
            f"RESEARCH COMPLETED: UNKNOWN "
            f"name={name_jp} uuid={uuid}"
        )
        log(
            f"reading_present={bool(reading)} "
            f"confidence={confidence}"
        )

    else:
        log("")
        log(
            f"RESEARCH SUCCESS "
            f"name={name_jp} "
            f"uuid={uuid} "
            f"reading={reading} "
            f"status={status} "
            f"confidence={confidence}"
        )

    # ------------------------------------------------------------
    # Save result
    # ------------------------------------------------------------
    try:
        saved = save_result(
            uuid,
            name_jp,
            result,
        )

    except Exception as e:
        fail_with_state(
            uuid,
            name_jp,
            "result_save_error",
            e,
        )

    if not saved:
        log(
            f"RESEARCH COMPLETED: EXISTING RESULT PROTECTED "
            f"name={name_jp} uuid={uuid}"
        )

        print(
            json.dumps(
                {
                    "uuid": uuid,
                    "name": name_jp,
                    "reading": reading,
                    "status": "skipped_existing_success",
                },
                ensure_ascii=False,
            )
        )

        sys.exit(0)

    # ------------------------------------------------------------
    # Final machine-readable summary
    # ------------------------------------------------------------
    print(
        json.dumps(
            {
                "uuid": uuid,
                "name": name_jp,
                "reading": reading,
                "status": status,
                "confidence": confidence,
                "checked_at": utc_now(),
            },
            ensure_ascii=False,
        )
    )

    log("")
    log(
        f"RESEARCH FINISHED "
        f"name={name_jp} uuid={uuid} "
        f"status={status}"
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
