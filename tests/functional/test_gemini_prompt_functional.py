import os
import json
import time
import pytest
from unittest.mock import patch, MagicMock

from src.server import process_inbound_queue


def poll_for_result(client, job_id, timeout=30):
    """Polls the outbound endpoint until the job is complete or times out."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        response = client.get(f'/outbound?job_id={job_id}')
        if response.status_code == 200:
            data = response.get_json()
            if data.get('status') in ['Completed', 'Failed']:
                return data
        time.sleep(0.5)
    return None


@pytest.mark.functional
class TestGeminiPromptFunctional:
    """
    Functional tests for the gemini_prompt action.
    """

    def test_gemini_prompt_text_success(self, client, app, monkeypatch):
        """Test sending a prompt and receiving text response."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello, this is Gemini answering your prompt."}]
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            response = client.post('/inbound', json={
                'action': 'gemini_prompt',
                'params': {
                    'prompt': 'Say hello',
                    'model': 'gemini-1.5-flash',
                    'json_output': False
                }
            })
            assert response.status_code == 200
            job_id = response.get_json()['job_id']
            time.sleep(0.1)

            process_inbound_queue(app, MagicMock(is_set=lambda: False))

            data = poll_for_result(client, job_id)
            assert data is not None, "Polling for result timed out."
            assert data['status'] == 'Completed'
            assert data['result'] == "Hello, this is Gemini answering your prompt."

            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            assert "gemini-1.5-flash:generateContent?key=test-api-key" in call_url

    def test_gemini_prompt_json_output(self, client, app, monkeypatch):
        """Test sending a prompt and requesting JSON output format."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        expected_json = {"answer": 42, "unit": "universal"}
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps(expected_json)}]
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            response = client.post('/inbound', json={
                'action': 'gemini_prompt',
                'params': {
                    'prompt': 'Give me the meaning of life in json',
                    'json_output': True
                }
            })
            assert response.status_code == 200
            job_id = response.get_json()['job_id']
            time.sleep(0.1)

            process_inbound_queue(app, MagicMock(is_set=lambda: False))

            data = poll_for_result(client, job_id)
            assert data is not None
            assert data['status'] == 'Completed'
            assert data['result'] == expected_json

            # Verify generationConfig was included in payload
            call_payload = mock_post.call_args[1]['json']
            assert call_payload['generationConfig']['responseMimeType'] == 'application/json'

    def test_gemini_prompt_with_files(self, client, app, tmp_path, monkeypatch):
        """Test sending a prompt with an attached file."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

        test_file = tmp_path / "sample.txt"
        test_file.write_text("Context document for Gemini.")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "File received and analyzed."}]
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            response = client.post('/inbound', json={
                'action': 'gemini_prompt',
                'params': {
                    'prompt': 'Summarize file',
                    'files': [str(test_file)],
                    'model': 'gemini-1.5-pro'
                }
            })
            assert response.status_code == 200
            job_id = response.get_json()['job_id']
            time.sleep(0.1)

            process_inbound_queue(app, MagicMock(is_set=lambda: False))

            data = poll_for_result(client, job_id)
            assert data is not None
            assert data['status'] == 'Completed'
            assert data['result'] == "File received and analyzed."

            call_payload = mock_post.call_args[1]['json']
            parts = call_payload['contents'][0]['parts']
            assert len(parts) == 2
            assert "inlineData" in parts[0]
            assert parts[0]['inlineData']['mimeType'] == 'text/plain'
            assert parts[1]['text'] == 'Summarize file'

    def test_gemini_prompt_missing_api_key(self, client, app, monkeypatch):
        """Test error handling when GEMINI_API_KEY is not set."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        response = client.post('/inbound', json={
            'action': 'gemini_prompt',
            'params': {
                'prompt': 'Test without key'
            }
        })
        assert response.status_code == 200
        job_id = response.get_json()['job_id']
        time.sleep(0.1)

        process_inbound_queue(app, MagicMock(is_set=lambda: False))

        data = poll_for_result(client, job_id)
        assert data is not None
        assert data['status'] == 'Failed'
        assert "GEMINI_API_KEY" in data['error']
