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
class TestOpenRouterPromptFunctional:
    """
    Functional tests for the openrouter_prompt action.
    """

    def test_openrouter_prompt_text_success(self, client, app, monkeypatch):
        """Test sending an openrouter_prompt and receiving text response."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-api-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Hello, this is OpenRouter answering your prompt."
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            response = client.post('/inbound', json={
                'action': 'openrouter_prompt',
                'params': {
                    'prompt': 'Say hello',
                    'model': 'openai/gpt-4o',
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
            assert data['result'] == "Hello, this is OpenRouter answering your prompt."

            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            assert call_url == "https://openrouter.ai/api/v1/chat/completions"

    def test_openrouter_prompt_json_output(self, client, app, monkeypatch):
        """Test sending an openrouter_prompt and requesting JSON output format."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-api-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        expected_json = {"answer": 42, "unit": "universal"}
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(expected_json)
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            response = client.post('/inbound', json={
                'action': 'openrouter_prompt',
                'params': {
                    'prompt': 'Give me JSON',
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

            call_payload = mock_post.call_args[1]['json']
            assert call_payload['response_format'] == {'type': 'json_object'}

    def test_openrouter_prompt_missing_api_key(self, client, app, monkeypatch):
        """Test error handling when OPENROUTER_API_KEY is not set."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        response = client.post('/inbound', json={
            'action': 'openrouter_prompt',
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
        assert "OPENROUTER_API_KEY" in data['error']
