import os
import json
import logging
import mimetypes
import base64
import requests

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _detect_mime_type(file_path):
    """Detect MIME type from file extension or content."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.jpg', '.jpeg']:
        return 'image/jpeg'
    elif ext == '.png':
        return 'image/png'
    elif ext == '.webp':
        return 'image/webp'
    elif ext == '.gif':
        return 'image/gif'
    elif ext == '.pdf':
        return 'application/pdf'
    elif ext in ['.txt', '.md', '.csv']:
        return 'text/plain'
    elif ext == '.json':
        return 'application/json'
    elif ext in ['.mp3', '.wav']:
        return 'audio/mp3'
    elif ext in ['.mp4', '.mov', '.avi', '.wmv']:
        return 'video/mp4'
    return 'application/octet-stream'


def call_gemini_api(prompt, files=None, json_output=False, model=None, api_key=None):
    """
    Calls the Gemini API generateContent endpoint with text prompt and optional files.
    """
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    model_version = model or DEFAULT_GEMINI_MODEL
    url = f"{GEMINI_API_BASE_URL}/{model_version}:generateContent?key={api_key}"

    parts = []

    # Process files if provided
    if files:
        for file_path in files:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")

            mime_type = _detect_mime_type(file_path)
            with open(file_path, "rb") as f:
                encoded_data = base64.b64encode(f.read()).decode("utf-8")

            parts.append({
                "inlineData": {
                    "mimeType": mime_type,
                    "data": encoded_data
                }
            })

    # Add text prompt
    if prompt:
        parts.append({"text": prompt})

    payload = {
        "contents": [
            {
                "parts": parts
            }
        ]
    }

    if json_output:
        payload["generationConfig"] = {
            "responseMimeType": "application/json"
        }

    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        raise RuntimeError(f"Gemini API error ({response.status_code}): {response.text}")

    resp_json = response.json()
    candidates = resp_json.get("candidates", [])
    if not candidates:
        raise ValueError(f"No candidates returned by Gemini API: {resp_json}")

    content = candidates[0].get("content", {})
    response_parts = content.get("parts", [])
    raw_text = "".join(part.get("text", "") for part in response_parts)

    if json_output:
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            # In case model wrapped in markdown code blocks: ```json ... ```
            cleaned = raw_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())

    return raw_text


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Executes a Gemini prompt action.
    Params:
      - prompt (str): Text prompt to send.
      - files (list of str, optional): File paths to include.
      - json_output (bool, optional): Whether to request and parse JSON output.
      - model (str, optional): Gemini model version (e.g. 'gemini-2.5-flash').
    """
    try:
        prompt = params.get("prompt", "")
        files = params.get("files", [])
        json_output = params.get("json_output", False)
        model = params.get("model")

        logging.info(
            f"Calling Gemini API for job {job_id} "
            f"(model: {model or DEFAULT_GEMINI_MODEL}, json_output: {json_output})"
        )
        api_result = call_gemini_api(prompt, files=files, json_output=json_output, model=model)

        result_data = {
            "job_id": job_id,
            "status": "Completed",
            "result": api_result
        }
        write_result_to_outbound(job_id, result_data)

    except Exception as e:
        logging.error(f"Error executing gemini_prompt action for job {job_id}: {e}")
        error_result = {
            "job_id": job_id,
            "status": "Failed",
            "error": str(e)
        }
        write_result_to_outbound(job_id, error_result)
