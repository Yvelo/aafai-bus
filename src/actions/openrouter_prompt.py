import os
import json
import logging
import mimetypes
import base64
import requests

DEFAULT_OPENROUTER_MODEL = "google/gemini-2.5-flash"
OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


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


def call_openrouter_api(prompt, files=None, json_output=False, model=None, api_key=None):
    """
    Calls the OpenRouter API chat completions endpoint with text prompt and optional files.
    """
    if not api_key:
        api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY environment variable is not set.")

    model_version = model or DEFAULT_OPENROUTER_MODEL
    url = OPENROUTER_API_BASE_URL

    content_items = []

    # Process files if provided
    if files:
        for file_path in files:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")

            mime_type = _detect_mime_type(file_path)
            if mime_type.startswith("image/"):
                with open(file_path, "rb") as f:
                    encoded_data = base64.b64encode(f.read()).decode("utf-8")
                content_items.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{encoded_data}"
                    }
                })
            else:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        text_content = f.read()
                    content_items.append({
                        "type": "text",
                        "text": f"--- Content of {os.path.basename(file_path)} ---\n{text_content}"
                    })
                except Exception:
                    with open(file_path, "rb") as f:
                        encoded_data = base64.b64encode(f.read()).decode("utf-8")
                    content_items.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{encoded_data}"
                        }
                    })

    # Add text prompt
    if prompt:
        content_items.append({"type": "text", "text": prompt})

    payload = {
        "model": model_version,
        "messages": [
            {
                "role": "user",
                "content": content_items
            }
        ]
    }

    if json_output:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/aafai-bus",
        "X-Title": "aafai-bus"
    }

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter API error ({response.status_code}): {response.text}")

    resp_json = response.json()
    choices = resp_json.get("choices", [])
    if not choices:
        raise ValueError(f"No choices returned by OpenRouter API: {resp_json}")

    raw_text = choices[0].get("message", {}).get("content", "")

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
    Executes an OpenRouter prompt action.
    Params:
      - prompt (str): Text prompt to send.
      - files (list of str, optional): File paths to include.
      - json_output (bool, optional): Whether to request and parse JSON output.
      - model (str, optional): OpenRouter model version (e.g. 'google/gemini-2.5-flash').
      - api_key (str, optional): Custom OpenRouter API key.
    """
    try:
        prompt = params.get("prompt", "")
        files = params.get("files", [])
        json_output = params.get("json_output", False)
        model = params.get("model")
        api_key = params.get("api_key")

        logging.info(
            f"Calling OpenRouter API for job {job_id} "
            f"(model: {model or DEFAULT_OPENROUTER_MODEL}, json_output: {json_output})"
        )
        api_result = call_openrouter_api(prompt, files=files, json_output=json_output, model=model, api_key=api_key)

        result_data = {
            "job_id": job_id,
            "status": "Completed",
            "result": api_result
        }
        write_result_to_outbound(job_id, result_data)

    except Exception as e:
        logging.error(f"Error executing openrouter_prompt action for job {job_id}: {e}")
        error_result = {
            "job_id": job_id,
            "status": "Failed",
            "error": str(e)
        }
        write_result_to_outbound(job_id, error_result)
