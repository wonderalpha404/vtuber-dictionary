#!/usr/bin/env python3

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests


VDB_PATH = "source/vdb.json"
RESULT_PATH = "source/vtuber-readings.json"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openrouter/free"

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 60


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    os.replace(temp_path, path)


def find_vtuber(vdb, uuid):
    for record in vdb.get("vtbs", []):
        if record.get("uuid") == uuid:
            return record

    return None


def get_japanese_name(record):
    name = record.get("name", {})

    if not isinstance(name, dict):
        return ""

    jp = name.get("jp")

    if not isinstance(jp, str):
        return ""

    return jp.strip()


def build_research_prompt(record):
    uuid = record.get("uuid", "")
    name = get_japanese_name(record)

    return f"""
あなたはVTuberデータベースの調査担当です。

以下のVTuberについて、日本語表記の正式な読み方を調査してください。

UUID:
{uuid}

名前:
{name}

目的:
VTuber名を日本語IME辞書に登録するため、名前の正確な読み方を取得します。

【最重要ルール】

1. 最終回答は必ずJSONオブジェクト1個だけにしてください。
2. JSON以外の文章を絶対に出力しないでください。
3. Markdownのコードブロックも使用しないでください。
4. 調査途中の説明、検索状況、推論、コメントなどを出力しないでください。
5. 読み方を確定できない場合でも、必ずJSONを返してください。
6. 読み方を推測してはいけません。
7. 漢字から一般的に推測できる読みだけを根拠にしてはいけません。
8. 検索結果に似た名前の別VTuberが出た場合、それを対象VTuberとして扱ってはいけません。
9. 名前とUUIDが一致する対象を優先してください。
10. 無限に検索を続けないでください。十分な証拠が得られなければunknownとして終了してください。

【調査優先順位】

第1優先:
- VTuber本人の公式プロフィール
- 公式サイト
- 公式SNS
- 公式YouTube等のプロフィール
- 所属事務所・公式運営ページ

第2優先:
- Wikipedia
- 信頼できるVTuberデータベース
- 日本語の信頼できるメディア・人物情報サイト

第3優先:
- 上記で不足する場合のみ、名前を完全一致させた追加検索

Wikipediaは第三者情報源として利用できます。
ただしWikipediaだけで確認できた場合、通常はconfidenceをmediumとしてください。

【別人判定】

名前が似ているだけの人物・VTuberは絶対に同一人物として扱わないでください。

特に、
{name}
と表記が少しでも異なる人物が検索結果に出た場合、
その人物の読みを今回の対象の読みとして採用しないでください。

【JSON形式】

必ず以下の形式だけを返してください。

{{
  "uuid": "{uuid}",
  "name": "{name}",
  "reading": "",
  "status": "unknown",
  "confidence": "unknown",
  "source": "",
  "source_type": "",
  "notes": ""
}}

【status】

verified:
信頼できる情報源によって読み方を確認できた場合。

review:
候補となる読みはあるが、十分な確証がない場合。

unknown:
信頼できる読みを確認できなかった場合。

【confidence】

high:
公式情報など非常に強い根拠がある。

medium:
Wikipedia、信頼できるVTuberデータベース、複数の第三者情報源などで確認できる。

review:
根拠が弱い、または情報源間に不一致がある。

unknown:
読みを確認できない。

【reading】

確認できた正式な日本語読みをひらがなで記入してください。

確認できない場合は空文字列にしてください。

絶対に推測で埋めないでください。

【source】

読み方を確認したURLを1つ以上記載してください。

確認できない場合は空文字列にしてください。

【source_type】

例えば以下を使用してください。

official
wikipedia
vtuber_database
media
other

確認できない場合は空文字列にしてください。

【notes】

必要な場合だけ簡潔に記載してください。

ただし、長い調査記録や検索ログは書かないでください。

最終出力はJSONオブジェクト1個だけです。
""".strip()


def extract_json_object(text):
    """
    AIがJSON以外の文字を少量含めた場合に備え、
    JSONオブジェクト部分だけを抽出する。

    ただし、自然言語の調査文章しか返っていない場合は
    JSONとして扱わず失敗にする。
    """

    text = text.strip()

    # 完全なJSON
    try:
        parsed = json.loads(text)

        if isinstance(parsed, dict):
            return parsed

    except json.JSONDecodeError:
        pass

    # ```json ... ``` の場合
    fenced = re.search(
        r"```(?:json)?\s*(\{.*\})\s*```",
        text,
        re.DOTALL,
    )

    if fenced:
        try:
            parsed = json.loads(fenced.group(1))

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    # 最初の { から最後の } まで
    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:
        candidate = text[start:end + 1]

        try:
            parsed = json.loads(candidate)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    return None


def validate_result(result, expected_uuid, expected_name):
    if not isinstance(result, dict):
        raise ValueError("AI response is not a JSON object")

    required_fields = [
        "uuid",
        "name",
        "reading",
        "status",
        "confidence",
        "source",
        "source_type",
        "notes",
    ]

    missing = [
        field
        for field in required_fields
        if field not in result
    ]

    if missing:
        raise ValueError(
            "Missing required fields: " + ", ".join(missing)
        )

    if result["uuid"] != expected_uuid:
        raise ValueError(
            f"UUID mismatch: expected={expected_uuid} "
            f"actual={result['uuid']}"
        )

    if result["name"] != expected_name:
        raise ValueError(
            f"name mismatch: expected={expected_name} "
            f"actual={result['name']}"
        )

    allowed_statuses = {
        "verified",
        "review",
        "unknown",
    }

    if result["status"] not in allowed_statuses:
        raise ValueError(
            f"Invalid status: {result['status']}"
        )

    allowed_confidence = {
        "high",
        "medium",
        "review",
        "unknown",
    }

    if result["confidence"] not in allowed_confidence:
        raise ValueError(
            f"Invalid confidence: {result['confidence']}"
        )

    reading = result["reading"]

    if not isinstance(reading, str):
        raise ValueError("reading must be a string")

    if result["status"] == "verified" and not reading.strip():
        raise ValueError(
            "verified result must have a non-empty reading"
        )

    if result["status"] == "unknown" and reading.strip():
        raise ValueError(
            "unknown result must have an empty reading"
        )

    return result


def save_success_result(result):
    results = load_json(RESULT_PATH)

    if not isinstance(results, list):
        raise ValueError(
            f"{RESULT_PATH} must contain a JSON array"
        )

    uuid = result["uuid"]

    existing_index = None

    for index, item in enumerate(results):
        if isinstance(item, dict) and item.get("uuid") == uuid:
            existing_index = index
            break

    result_to_save = {
        "uuid": result["uuid"],
        "name": result["name"],
        "reading": result["reading"],
        "source": result["source"],
        "source_type": result["source_type"],
        "confidence": result["confidence"],
        "status": result["status"],
        "notes": result["notes"],
        "checked_at": utc_now(),
    }

    if existing_index is None:
        results.append(result_to_save)
    else:
        existing = results[existing_index]

        # 既存の成功データを守る。
        # 新しい成功結果だけを更新する。
        if existing.get("status") in {
            "verified",
            "review",
            "unknown",
        }:
            results[existing_index] = result_to_save
        else:
            results[existing_index] = result_to_save

    save_json(RESULT_PATH, results)


def save_failure_state(uuid, name):
    """
    詳細なエラー内容は保存しない。

    保存するのは「失敗した」という状態だけ。
    """

    results = load_json(RESULT_PATH)

    if not isinstance(results, list):
        raise ValueError(
            f"{RESULT_PATH} must contain a JSON array"
        )

    attempted_at = utc_now()

    failure_state = {
        "uuid": uuid,
        "name": name,
        "reading": "",
        "source": "",
        "source_type": "",
        "confidence": "unknown",
        "status": "pending",
        "notes": "",
        "checked_at": "",
        "last_attempted_at": attempted_at,
        "last_attempt_result": "error",
    }

    existing_index = None

    for index, item in enumerate(results):
        if isinstance(item, dict) and item.get("uuid") == uuid:
            existing_index = index
            break

    if existing_index is None:
        results.append(failure_state)
    else:
        existing = results[existing_index]

        # 既存の成功結果を失敗で壊さない。
        if existing.get("status") in {
            "verified",
            "review",
            "unknown",
        }:
            print(
                f"FAILURE STATE NOT OVERWRITTEN "
                f"name={name} uuid={uuid}",
                file=sys.stderr,
            )
        else:
            results[existing_index] = failure_state

    save_json(RESULT_PATH, results)

    print(
        f"FAILURE STATE SAVED "
        f"name={name} uuid={uuid} "
        f"status=pending "
        f"last_attempt_result=error",
        file=sys.stderr,
    )


def call_openrouter(prompt, uuid, name):
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set"
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "response_format": {
            "type": "json_object"
        },
        "tools": [
            {
                "type": "openrouter:web_search"
            }
        ],
    }

    print(
        "OPENROUTER REQUEST",
        file=sys.stderr,
    )
    print(
        f"name={name}",
        file=sys.stderr,
    )
    print(
        f"uuid={uuid}",
        file=sys.stderr,
    )
    print(
        f"model={OPENROUTER_MODEL}",
        file=sys.stderr,
    )
    print(
        "web_search=true",
        file=sys.stderr,
    )
    print(
        f"connect_timeout={CONNECT_TIMEOUT}s "
        f"read_timeout={READ_TIMEOUT}s",
        file=sys.stderr,
    )
    print(
        "max_attempts=1",
        file=sys.stderr,
    )

    started = time.monotonic()

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT,
            ),
        )
    except requests.exceptions.Timeout as exc:
        elapsed = time.monotonic() - started

        print(
            f"OPENROUTER TIMEOUT "
            f"name={name} uuid={uuid} "
            f"elapsed={elapsed:.1f}s",
            file=sys.stderr,
        )

        raise RuntimeError(
            "OpenRouter request timed out"
        ) from exc

    except requests.exceptions.RequestException as exc:
        elapsed = time.monotonic() - started

        print(
            f"OPENROUTER REQUEST ERROR "
            f"name={name} uuid={uuid} "
            f"elapsed={elapsed:.1f}s "
            f"error_type={type(exc).__name__}",
            file=sys.stderr,
        )

        raise RuntimeError(
            f"OpenRouter request failed: {type(exc).__name__}"
        ) from exc

    elapsed = time.monotonic() - started

    print(
        f"OPENROUTER HTTP RESPONSE "
        f"name={name} uuid={uuid} "
        f"status={response.status_code} "
        f"elapsed={elapsed:.1f}s "
        f"bytes={len(response.content)}",
        file=sys.stderr,
    )

    if response.status_code != 200:
        preview = response.text[:500]

        print(
            "OPENROUTER ERROR RESPONSE PREVIEW:",
            file=sys.stderr,
        )
        print(
            preview,
            file=sys.stderr,
        )

        raise RuntimeError(
            f"OpenRouter HTTP {response.status_code}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError(
            "OpenRouter returned invalid JSON"
        ) from exc

    print(
        f"OPENROUTER RESPONSE STRUCTURE "
        f"name={name} uuid={uuid} "
        f"top_level_keys={list(data.keys())}",
        file=sys.stderr,
    )

    choices = data.get("choices")

    if not isinstance(choices, list) or not choices:
        raise ValueError(
            "OpenRouter response contains no choices"
        )

    print(
        f"OPENROUTER CHOICES "
        f"name={name} uuid={uuid} "
        f"count={len(choices)}",
        file=sys.stderr,
    )

    message = choices[0].get("message")

    if not isinstance(message, dict):
        raise ValueError(
            "OpenRouter response contains no message"
        )

    print(
        f"OPENROUTER MESSAGE FOUND "
        f"name={name} uuid={uuid} "
        f"message_keys={list(message.keys())}",
        file=sys.stderr,
    )

    content = message.get("content")

    if not isinstance(content, str):
        raise ValueError(
            "OpenRouter message content is not a string"
        )

    print(
        f"OPENROUTER AI CONTENT RECEIVED "
        f"name={name} uuid={uuid} "
        f"content_length={len(content)}",
        file=sys.stderr,
    )

    return content


def main():
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/research_one_vtuber.py <uuid>",
            file=sys.stderr,
        )
        return 1

    uuid = sys.argv[1]

    print(
        "RESEARCH START",
        file=sys.stderr,
    )
    print(
        f"uuid={uuid}",
        file=sys.stderr,
    )

    try:
        vdb = load_json(VDB_PATH)
    except Exception as exc:
        print(
            f"RESEARCH FAILED "
            f"name=UNKNOWN uuid={uuid} "
            f"error_type=vdb_load_error "
            f"message={exc}",
            file=sys.stderr,
        )
        return 1

    record = find_vtuber(vdb, uuid)

    if record is None:
        print(
            f"RESEARCH FAILED "
            f"name=UNKNOWN uuid={uuid} "
            f"error_type=vtuber_not_found",
            file=sys.stderr,
        )
        return 1

    name = get_japanese_name(record)

    if not name:
        print(
            f"RESEARCH FAILED "
            f"name={name} uuid={uuid} "
            f"error_type=missing_japanese_name",
            file=sys.stderr,
        )
        return 1

    print(
        f"RESEARCH TARGET name={name} uuid={uuid}",
        file=sys.stderr,
    )

    prompt = build_research_prompt(record)

    print(
        f"RESEARCH PROMPT READY "
        f"name={name} uuid={uuid} "
        f"prompt_length={len(prompt)}",
        file=sys.stderr,
    )

    checked_at = utc_now()

    try:
        content = call_openrouter(
            prompt=prompt,
            uuid=uuid,
            name=name,
        )

        print(
            f"AI RESPONSE RECEIVED "
            f"name={name} "
            f"content_length={len(content)}",
            file=sys.stderr,
        )

        result = extract_json_object(content)

        if result is None:
            print(
                f"AI RESPONSE PARSE FAILED "
                f"name={name} "
                f"error_type=invalid_json",
                file=sys.stderr,
            )

            print(
                "AI RESPONSE START PREVIEW: "
                + content[:500],
                file=sys.stderr,
            )

            print(
                "AI RESPONSE END PREVIEW: "
                + content[-500:],
                file=sys.stderr,
            )

            raise ValueError(
                "Failed to parse AI response as a JSON object"
            )

        result = validate_result(
            result=result,
            expected_uuid=uuid,
            expected_name=name,
        )

        print(
            f"AI RESPONSE PARSED "
            f"name={name} "
            f"status={result['status']} "
            f"confidence={result['confidence']} "
            f"reading_present={bool(result['reading'])} "
            f"source_present={bool(result['source'])}",
            file=sys.stderr,
        )

        result["checked_at"] = checked_at

        save_success_result(result)

        print(
            f"RESEARCH SUCCESS "
            f"name={name} uuid={uuid} "
            f"reading={result['reading']} "
            f"status={result['status']} "
            f"confidence={result['confidence']}",
            file=sys.stderr,
        )

        print(
            f"RESULT SAVED "
            f"name={name} uuid={uuid} "
            f"status={result['status']} "
            f"confidence={result['confidence']}",
            file=sys.stderr,
        )

        print(
            f"RESEARCH FINISHED "
            f"name={name} uuid={uuid} "
            f"status={result['status']}",
            file=sys.stderr,
        )

        print(
            json.dumps(
                {
                    "uuid": result["uuid"],
                    "name": result["name"],
                    "reading": result["reading"],
                    "status": result["status"],
                    "confidence": result["confidence"],
                    "checked_at": result["checked_at"],
                },
                ensure_ascii=False,
            )
        )

        return 0

    except Exception as exc:
        print(
            f"RESEARCH FAILED "
            f"name={name} uuid={uuid} "
            f"error_type={type(exc).__name__} "
            f"message={exc}",
            file=sys.stderr,
        )

        try:
            save_failure_state(
                uuid=uuid,
                name=name,
            )
        except Exception as save_exc:
            print(
                f"FAILURE STATE SAVE ERROR "
                f"name={name} uuid={uuid} "
                f"error_type={type(save_exc).__name__} "
                f"message={save_exc}",
                file=sys.stderr,
            )

        return 1


if __name__ == "__main__":
    sys.exit(main())
