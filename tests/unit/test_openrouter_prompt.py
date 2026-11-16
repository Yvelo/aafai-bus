import os
import json
import pytest
from unittest.mock import MagicMock, patch

from src.actions.openrouter_prompt import call_openrouter_api, execute, DEFAULT_OPENROUTER_MODEL
from src.actions.solve_captcha import solve_captcha


def test_call_openrouter_api_missing_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY environment variable is not set."):
        call_openrouter_api("Hello")


def test_call_openrouter_api_text_success(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Response from OpenRouter model."
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = call_openrouter_api("Say hi", model="openai/gpt-4o")

    assert result == "Response from OpenRouter model."
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-or-key"
    assert call_kwargs["json"]["model"] == "openai/gpt-4o"
    assert call_kwargs["json"]["messages"][0]["content"] == [{"type": "text", "text": "Say hi"}]


def test_call_openrouter_api_json_output(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    expected_data = {"key": "value", "count": 10}
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": f"```json\n{json.dumps(expected_data)}\n```"
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = call_openrouter_api("Return json", json_output=True)

    assert result == expected_data
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["json"]["response_format"] == {"type": "json_object"}


def test_call_openrouter_api_files(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")

    img_file = tmp_path / "test.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    txt_file = tmp_path / "test.txt"
    txt_file.write_text("Hello from file")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Processed files successfully."}}]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = call_openrouter_api("Analyze files", files=[str(img_file), str(txt_file)])

    assert result == "Processed files successfully."
    content_items = mock_post.call_args[1]["json"]["messages"][0]["content"]
    assert len(content_items) == 3
    assert content_items[0]["type"] == "image_url"
    assert "data:image/png;base64," in content_items[0]["image_url"]["url"]
    assert content_items[1]["type"] == "text"
    assert "--- Content of test.txt ---" in content_items[1]["text"]
    assert content_items[2]["type"] == "text"
    assert content_items[2]["text"] == "Analyze files"


def test_execute_openrouter_prompt_success(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")

    mock_write_result = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Action completed"}}]
    }

    params = {
        "prompt": "Run openrouter action",
        "model": "google/gemini-2.5-flash"
    }

    with patch("requests.post", return_value=mock_response):
        execute("job-123", params, "/tmp", mock_write_result)

    mock_write_result.assert_called_once_with(
        "job-123",
        {
            "job_id": "job-123",
            "status": "Completed",
            "result": "Action completed"
        }
    )


def test_solve_captcha_uses_openrouter_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    image = tmp_path / "captcha.png"
    image.write_bytes(b"image")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"matrix": [[true, false]], "rows": 1, "cols": 2}'}}]
    }

    with patch("requests.post", return_value=mock_response) as post:
        res = solve_captcha(str(image), provider="openrouter", model="google/gemini-2.5-flash")

    assert res["matrix"] == [[True, False]]
    assert post.call_args[0][0] == "https://openrouter.ai/api/v1/chat/completions"
