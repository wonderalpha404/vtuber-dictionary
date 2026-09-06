#!/usr/bin/env python3
"""Research script for a single vtuber using OpenRouter API with web search."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional
import requests


def load_json_file(file_path: str) -> Any:
    """Load JSON file with error handling."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {file_path}", file=sys.stderr)
        sys.exit(1)


def find_vtuber_entry(data: list, name: str) -> dict:
    """Find a single vtuber entry by exact name match."""
    matches = [entry for entry in data if entry.get('name') == name]
    
    if len(matches) == 0:
        print(f"Error: VTuber '{name}' not found", file=sys.stderr)
        sys.exit(1)
    elif len(matches) > 1:
        print(f"Error: Multiple entries found for '{name}'", file=sys.stderr)
        sys.exit(1)
    
    return matches[0]


def find_vdb_entry(vdb_data: dict, uuid: str) -> Optional[dict]:
    """Find VTuber entry in VDB by UUID."""
    vtubers = vdb_data.get('vtubers', [])
    for vtuber in vtubers:
        if vtuber.get('uuid') == uuid:
            return vtuber
    return None


def build_auxiliary_info(vdb_entry: Optional[dict]) -> str:
    """Build auxiliary information from VDB entry."""
    if not vdb_entry:
        return ""
    
    aux_lines = []
    name_obj = vdb_entry.get('name', {})
    
    for key in ['jp', 'cn', 'en', 'default', 'extra']:
        if key in name_obj:
            value = name_obj[key]
            if isinstance(value, list):
                aux_lines.append(f"  {key}: {', '.join(value)}")
            else:
                aux_lines.append(f"  {key}: {value}")
    
    return "\n".join(aux_lines) if aux_lines else ""


def build_research_prompt(entry: dict, aux_info: str) -> str:
    """Build the research prompt for AI."""
    prompt = f"""Please research the reading of the following VTuber's name using web search.

VTuber Information:
- Name: {entry['name']}
- UUID: {entry['uuid']}
- Reading: {entry['reading']}
- Source: {entry['source']}
- Source Type: {entry['source_type']}
- Confidence: {entry['confidence']}
- Status: {entry['status']}
- Checked At: {entry['checked_at']}
- Notes: {entry['notes']}

Auxiliary Name Information from VDB:
{aux_info if aux_info else "  No auxiliary information available"}

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
  "name": "",
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
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        print("Error: OPENROUTER_API_KEY environment variable is not set", file=sys.stderr)
        sys.exit(1)
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        }
                    },
                    "required": ["query"]
                }
            }
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
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print("Error: Network connection failed", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("Error: Request timeout", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"Error: HTTP error - {e.response.status_code}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error: Request failed - {e}", file=sys.stderr)
        sys.exit(1)
    
    try:
        response_data = response.json()
    except json.JSONDecodeError:
        print("Error: OpenRouter response is not valid JSON", file=sys.stderr)
        sys.exit(1)
    
    if 'choices' not in response_data:
        print("Error: 'choices' field not found in API response", file=sys.stderr)
        sys.exit(1)
    
    choices = response_data.get('choices', [])
    if not choices:
        print("Error: Empty choices array in API response", file=sys.stderr)
        sys.exit(1)
    
    message = choices[0].get('message')
    if not message:
        print("Error: No message in response", file=sys.stderr)
        sys.exit(1)
    
    content = message.get('content')
    if not content:
        print("Error: No content in assistant message", file=sys.stderr)
        sys.exit(1)
    
    return content


def parse_ai_response(content: str) -> dict:
    """Parse and validate AI response JSON."""
    # Remove markdown code fences if present
    content = content.strip()
    if content.startswith('```'):
        lines = content.split('\n')
        content = '\n'.join(lines[1:])  # Remove first line (```)
        if content.endswith('```'):
            content = content[:-3]  # Remove last line (```)
        content = content.strip()
    
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        print("Error: Failed to parse AI response as JSON", file=sys.stderr)
        sys.exit(1)
    
    # Validate structure
    if not isinstance(result, dict):
        print("Error: AI response is not a JSON object", file=sys.stderr)
        sys.exit(1)
    
    required_keys = ['name', 'reading', 'source', 'source_type', 'confidence', 'status', 'notes']
    for key in required_keys:
        if key not in result:
            print(f"Error: Missing required key in AI response: {key}", file=sys.stderr)
            sys.exit(1)
    
    # Validate name matches
    if result['name'] != 'P丸様':
        print(f"Error: AI response name '{result['name']}' does not match 'P丸様'", file=sys.stderr)
        sys.exit(1)
    
    # Validate confidence value
    valid_confidences = ['high', 'medium', 'review', 'unknown']
    if result['confidence'] not in valid_confidences:
        print(f"Error: Invalid confidence value: {result['confidence']}", file=sys.stderr)
        sys.exit(1)
    
    # Validate status value
    valid_statuses = ['verified', 'review', 'unknown']
    if result['status'] not in valid_statuses:
        print(f"Error: Invalid status value: {result['status']}", file=sys.stderr)
        sys.exit(1)
    
    # Validate source requirements
    if not result['source'] and result['confidence'] != 'unknown':
        print("Error: source must be non-empty if confidence is not 'unknown'", file=sys.stderr)
        sys.exit(1)
    
    if result['confidence'] in ['high', 'medium', 'review'] and not result['source']:
        print(f"Error: source cannot be empty when confidence is '{result['confidence']}'", file=sys.stderr)
        sys.exit(1)
    
    return result


def main():
    """Main execution function."""
    script_dir = Path(__file__).parent.parent
    sample_file = script_dir / 'source' / 'sample-10-jp.json'
    vdb_file = script_dir / 'source' / 'vdb.json'
    
    # Load input files
    sample_data = load_json_file(str(sample_file))
    vdb_data = load_json_file(str(vdb_file))
    
    # Find target entry
    entry = find_vtuber_entry(sample_data, 'P丸様')
    
    # Find auxiliary info from VDB
    vdb_entry = find_vdb_entry(vdb_data, entry['uuid'])
    aux_info = build_auxiliary_info(vdb_entry)
    
    # Build research prompt
    prompt = build_research_prompt(entry, aux_info)
    
    # Call OpenRouter API (1 call only)
    ai_response = call_openrouter_api(prompt)
    
    # Parse and validate response
    result = parse_ai_response(ai_response)
    
    # Output result
    print("Research result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
