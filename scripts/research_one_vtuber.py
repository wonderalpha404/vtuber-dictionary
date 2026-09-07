#!/usr/bin/env python3
"""Research script for a single vtuber using OpenRouter API with web search.

Now accepts a UUID as sole positional argument. Uses source/vdb.json (read-only)
to find the vtuber entry and its name.jp. On success, writes/updates
source/vtuber-readings.json (array) with a single clean record for the uuid.

On failure, writes a minimal failure-state record into source/vtuber-readings.json
for that uuid (unless an existing successful result exists), without storing
detailed stderr or AI response. Exits with non-zero on failure.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests


def load_json_file(file_path: str) -> Any:
    """Load JSON file with error handling."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {file_path}: {e}", file=sys.stderr)
        sys.exit(1)


def find_vdb_entry_by_uuid(vdb_data: dict, uuid: str) -> Optional[dict]:
    """Find VTuber entry in VDB by UUID."""
    vtbs = vdb_data.get("vtbs", [])
    for vtuber in vtbs:
        if vtuber.get("uuid") == uuid:
            return vtuber
    return None


def build_auxiliary_info(vdb_entry: Optional[dict]) -> str:
    """Build auxiliary information from VDB entry."""
    if not vdb_entry:
        return ""

    aux_lines = []
    name_obj = vdb_entry.get("name", {})

    for key in ["jp", "cn", "en", "default", "extra"]:
        if key in name_obj:
            value = name_obj[key]
            if isinstance(value, list):
                aux_lines.append(f"  {key}: {', '.join(value)}")
            else:
                aux_lines.append(f"  {key}: {value}")

    return "\n".join(aux_lines) if aux_lines else ""


def build_research_prompt(name_jp: str, uuid: str, entry: dict, aux_info: str) -> str:
    """Build the research prompt for AI."""
    prompt = f"""Please research the reading of the following VTuber's name using web search.

VTuber Information:
- Name: {name_jp}
- UUID: {uuid}
- Auxiliary info:
{aux_info if aux_info else '  No auxiliary information available'}

Instructions:
1. Do NOT guess the reading. Use only web search to find evidence.
2. Set reading only if you find reliable sources.
3. Priority for sources (in order):
   - Official website, official profile, official SNS, official videos/streams
   - Trustworthy third-party information
4. Prohibitions:
   - Do NOT infer reading from general kanji pronunciation
   - Do NOT use "this name is typically read this way" reasoning
   - Do NOT rely only on search snippet previews - verify from the actual page if possible
   - Do NOT use information about a different person or VTuber
5. If multiple reliable sources agree on the reading, set confidence to "high"
6. If only trustworthy third-party sources match, set confidence to "medium"
7. If sources contradict each other, set confidence to "review"
8. If no evidence is found, set confidence to "unknown" and do NOT guess
9. Always record the source URLs in the notes
10. Do NOT fabricate URLs

Respond ONLY with a valid JSON object (no markdown formatting, no extra text):
{{
  "name": "{name_jp}",
  "reading": "",
  "source": "",
  "source_type": "",
  "confidence": "high|medium|review|unknown",
  "status": "verified|review|unknown",
  "notes": ""
}}"""
    return prompt


def call_openrouter_api(prompt: str) -> str:
    """Call OpenRouter API with web search tool."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print(
            "Error: OPENROUTER_API_KEY environment variable is not set",
            file=sys.stderr,
        )
        sys.exit(1)

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # OpenRouter server-side Web Search tool.
    tools = [
        {
            "type": "openrouter:web_search"
        }
    ]

    payload = {
        "model": "openrouter/free",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "tools": tools,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print("Error: Network connection failed", file=sys.stderr)
        raise
    except requests.exceptions.Timeout:
        print("Error: Request timeout", file=sys.stderr)
        raise
    except requests.exceptions.HTTPError as e:
        print(
            f"Error: HTTP error - {e.response.status_code}",
            file=sys.stderr,
        )
        raise
    except requests.exceptions.RequestException as e:
        print(f"Error: Request failed - {e}", file=sys.stderr)
        raise

    try:
        response_data = response.json()
    except json.JSONDecodeError as e:
        # Provide details for logging; do not store in JSON file
        print(f"Error: OpenRouter response is not valid JSON: {e}", file=sys.stderr)
        raise

    if "choices" not in response_data:
        print(
            "Error: 'choices' field not found in API response",
            file=sys.stderr,
        )
        raise ValueError("'choices' not found")

    choices = response_data.get("choices", [])
    if not choices:
        print(
            "Error: Empty choices array in API response",
            file=sys.stderr,
        )
        raise ValueError("empty choices")

    message = choices[0].get("message")
    if not message:
        print("Error: No message in response", file=sys.stderr)
        raise ValueError("no message")

    content = message.get("content")
    if not content:
        print(
            "Error: No content in assistant message",
            file=sys.stderr,
        )
        raise ValueError("no content")

    return content


def parse_ai_response(content: str, expected_name: str) -> dict:
    """Parse and validate AI response JSON."""
    content = content.strip()

    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        # Provide detailed JSON error info per spec
        print(f"Error: Failed to parse AI response as JSON: {e}", file=sys.stderr)
        raise

    if not isinstance(result, dict):
        print(
            "Error: AI response is not a JSON object",
            file=sys.stderr,
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

    for key in required_keys:
        if key not in result:
            print(
                f"Error: Missing required key in AI response: {key}",
                file=sys.stderr,
            )
            raise ValueError(f"Missing required key: {key}")

    if result["name"] != expected_name:
        print(
            f"Error: AI response name '{result['name']}' does not match expected '{expected_name}'",
            file=sys.stderr,
        )
        raise ValueError("AI response name mismatch")

    valid_confidences = [
        "high",
        "medium",
        "review",
        "unknown",
    ]

    if result["confidence"] not in valid_confidences:
        print(
            f"Error: Invalid confidence value: {result['confidence']}",
            file=sys.stderr,
        )
        raise ValueError("Invalid confidence")

    valid_statuses = [
        "verified",
        "review",
        "unknown",
    ]

    if result["status"] not in valid_statuses:
        print(
            f"Error: Invalid status value: {result['status']}",
            file=sys.stderr,
        )
        raise ValueError("Invalid status")

    if not result["source"] and result["confidence"] != "unknown":
        print(
            "Error: source must be non-empty if confidence is not 'unknown'",
            file=sys.stderr,
        )
        raise ValueError("Missing source for non-unknown confidence")

    if (
        result["confidence"] in ["high", "medium", "review"]
        and not result["source"]
    ):
        print(
            "Error: source cannot be empty when confidence is "
            f"'{result['confidence']}'",
            file=sys.stderr,
        )
        raise ValueError("Missing source for confidence")

    return result


def load_readings() -> list:
    READINGS_PATH = Path(__file__).resolve().parent.parent / "source" / "vtuber-readings.json"
    try:
        with READINGS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                print(f"Error: {READINGS_PATH} is not an array", file=sys.stderr)
                sys.exit(1)
            return data
    except FileNotFoundError:
        return []


def write_readings(new_list: list) -> None:
    READINGS_PATH = Path(__file__).resolve().parent.parent / "source" / "vtuber-readings.json"
    with READINGS_PATH.open("w", encoding="utf-8") as f:
        json.dump(new_list, f, ensure_ascii=False, indent=2)
        f.write("\n")


def save_result(uuid: str, name_jp: str, ai_result: dict) -> bool:
    """
    Save or update the result for uuid in source/vtuber-readings.json.
    Do NOT overwrite an existing successful record (verified/review/unknown).
    Returns True if file was written/updated, False if skipped due to existing success.
    Raises exception on write failure.
    """
    now_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "uuid": uuid,
        "name": name_jp,
        "reading": ai_result["reading"],
        "source": ai_result["source"],
        "source_type": ai_result["source_type"],
        "confidence": ai_result["confidence"],
        "status": ai_result["status"],
        "notes": ai_result.get("notes", ""),
        "checked_at": now_utc,
    }

    readings = load_readings()
    for i, r in enumerate(readings):
        if r.get("uuid") == uuid:
            # Protect existing successful result
            if r.get("status") in ["verified", "review", "unknown"]:
                # Do not overwrite; return False to indicate skip
                print(f"Info: existing successful result for uuid={uuid} present; not overwriting.", file=sys.stderr)
                return False
            readings[i] = record
            write_readings(readings)
            return True

    # not found -> append
    readings.append(record)
    write_readings(readings)
    return True


def save_failure_state(uuid: str, name_jp: str) -> None:
    """
    Save minimal failure state to vtuber-readings.json for the uuid.
    Do NOT overwrite an existing successful result (verified/review/unknown).
    Do NOT store stderr/exception details or AI response.
    Raises exception if writing fails.
    """
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
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
    for i, r in enumerate(readings):
        if r.get("uuid") == uuid:
            if r.get("status") in ["verified", "review", "unknown"]:
                # Do not overwrite existing success
                return
            readings[i] = fail_record
            write_readings(readings)
            return
    # not present -> append
    readings.append(fail_record)
    write_readings(readings)


def main():
    if len(sys.argv) < 2:
        print("Error: UUID must be provided as a command-line argument", file=sys.stderr)
        sys.exit(1)

    uuid = sys.argv[1]
    script_dir = Path(__file__).resolve().parent.parent

    vdb_file = script_dir / "source" / "vdb.json"

    # Load VDB
    try:
        vdb_data = load_json_file(str(vdb_file))
    except SystemExit:
        sys.exit(1)

    entry = find_vdb_entry_by_uuid(vdb_data, uuid)
    if not entry:
        print(f"Error: VTuber UUID '{uuid}' not found in {vdb_file}", file=sys.stderr)
        sys.exit(1)

    # Extract name.jp
    name_obj = entry.get("name", {})
    name_jp = name_obj.get("jp")
    if not name_jp or (isinstance(name_jp, str) and name_jp.strip() == ""):
        print(f"Error: name.jp missing or empty for uuid={uuid}", file=sys.stderr)
        sys.exit(1)

    aux_info = build_auxiliary_info(entry)
    prompt = build_research_prompt(name_jp, uuid, entry, aux_info)

    # Call OpenRouter/API and parse. On any failure, save minimal failure state and exit non-zero.
    try:
        ai_response = call_openrouter_api(prompt)
    except Exception as e:
        # Network/API error; log brief reason and save failure state
        print(f"Error: OpenRouter/API call failed: {e}", file=sys.stderr)
        try:
            save_failure_state(uuid, name_jp)
        except Exception as se:
            print(f"Error: Failed to save failure state for uuid={uuid}: {se}", file=sys.stderr)
        sys.exit(1)

    # Parse AI response
    try:
        result = parse_ai_response(ai_response, name_jp)
    except json.JSONDecodeError as e:
        # Detailed JSON parsing info per spec, do not save full response
        print(f"Error: Failed to parse AI response as JSON: {e}", file=sys.stderr)
        try:
            save_failure_state(uuid, name_jp)
        except Exception as se:
            print(f"Error: Failed to save failure state for uuid={uuid}: {se}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # Validation error; log and save minimal failure state
        print(f"Error: AI response validation failed: {e}", file=sys.stderr)
        try:
            save_failure_state(uuid, name_jp)
        except Exception as se:
            print(f"Error: Failed to save failure state for uuid={uuid}: {se}", file=sys.stderr)
        sys.exit(1)

    # Additional validation: if status is verified/review, reading must be non-empty.
    try:
        status = result.get("status")
        reading = result.get("reading", "")
        if status in ["verified", "review"]:
            if not isinstance(reading, str) or reading.strip() == "":
                # Treat as failure per spec: do not accept success, save minimal failure state and exit non-zero.
                print(f"Error: AI returned status={status} but reading is empty; treating as failure.", file=sys.stderr)
                try:
                    save_failure_state(uuid, name_jp)
                except Exception as se:
                    print(f"Error: Failed to save failure state for uuid={uuid}: {se}", file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        # On any unexpected error here, do not overwrite existing successes; attempt to save failure state and exit
        print(f"Error: Unexpected validation error: {e}", file=sys.stderr)
        try:
            save_failure_state(uuid, name_jp)
        except Exception as se:
            print(f"Error: Failed to save failure state for uuid={uuid}: {se}", file=sys.stderr)
        sys.exit(1)

    # Before saving, check existing success and do not overwrite
    try:
        saved = save_result(uuid, name_jp, result)
    except Exception as e:
        print(f"Error: Failed to save result: {e}", file=sys.stderr)
        try:
            save_failure_state(uuid, name_jp)
        except Exception as se:
            print(f"Error: Failed to save failure state for uuid={uuid}: {se}", file=sys.stderr)
        sys.exit(1)

    if not saved:
        # existing successful record present; do not overwrite; treat as non-error and exit 0
        print(f"Info: existing successful result for uuid={uuid} exists; not overwriting.", file=sys.stderr)
        print(json.dumps({
            "uuid": uuid,
            "name": name_jp,
            "reading": result.get("reading", ""),
            "status": "skipped_existing_success"
        }, ensure_ascii=False))
        sys.exit(0)

    # Print summary (not full AI response)
    print("Research result saved:")
    print(json.dumps({
        "uuid": uuid,
        "name": name_jp,
        "reading": result["reading"],
        "status": result["status"],
        "checked_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    }, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
