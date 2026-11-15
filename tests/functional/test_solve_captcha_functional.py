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
class TestSolveCaptchaFunctional:
    """
    Functional tests for the solve_captcha action.
    """

    def test_solve_captcha_3x3_with_static_image(self, client, app, monkeypatch):
        """Test solve_captcha action with the static test_captcha.png image."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

        project_root = app.config['BASE_QUEUE_PATH']
        # Locate static/test_captcha.png relative to project root
        static_captcha_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../../static/test_captcha.png')
        )
        assert os.path.exists(static_captcha_path), f"Test image not found at {static_captcha_path}"

        expected_matrix = [
            [True, False, False],
            [False, True, False],
            [True, True, False]
        ]
        gemini_response_payload = {
            "rows": 3,
            "cols": 3,
            "target": "crosswalks",
            "matrix": expected_matrix
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps(gemini_response_payload)}]
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            response = client.post('/inbound', json={
                'action': 'solve_captcha',
                'params': {
                    'image_path': static_captcha_path
                }
            })
            assert response.status_code == 200
            job_id = response.get_json()['job_id']
            time.sleep(0.1)

            process_inbound_queue(app, MagicMock(is_set=lambda: False))

            data = poll_for_result(client, job_id)
            assert data is not None, "Polling for result timed out."
            assert data['status'] == 'Completed'

            result = data['result']
            assert 'matrix' in result
            assert result['rows'] == 3
            assert result['cols'] == 3
            assert result['matrix'] == expected_matrix
            # Verify every row has 3 items and all items are booleans
            assert len(result['matrix']) == 3
            for row in result['matrix']:
                assert len(row) == 3
                for cell in row:
                    assert isinstance(cell, bool)

            # Verify API call sent image data
            mock_post.assert_called_once()
            call_payload = mock_post.call_args[1]['json']
            parts = call_payload['contents'][0]['parts']
            assert any('inlineData' in p and p['inlineData']['mimeType'] == 'image/png' for p in parts)

    def test_solve_captcha_4x4_dynamic_dimension(self, client, app, tmp_path, monkeypatch):
        """Test solve_captcha action handling a 4x4 captcha grid."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

        # Create a dummy jpg file
        dummy_jpg = tmp_path / "captcha_4x4.jpg"
        dummy_jpg.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb")

        expected_matrix = [
            [False, True, False, False],
            [False, True, True, False],
            [False, False, True, False],
            [False, False, False, False]
        ]
        gemini_response_payload = {
            "rows": 4,
            "cols": 4,
            "target": "traffic lights",
            "matrix": expected_matrix
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps(gemini_response_payload)}]
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_response):
            response = client.post('/inbound', json={
                'action': 'solve_captcha',
                'params': {
                    'image_path': str(dummy_jpg)
                }
            })
            assert response.status_code == 200
            job_id = response.get_json()['job_id']
            time.sleep(0.1)

            process_inbound_queue(app, MagicMock(is_set=lambda: False))

            data = poll_for_result(client, job_id)
            assert data is not None
            assert data['status'] == 'Completed'

            result = data['result']
            assert result['rows'] == 4
            assert result['cols'] == 4
            assert len(result['matrix']) == 4
            assert len(result['matrix'][0]) == 4

    def test_solve_captcha_invalid_format(self, client, app, tmp_path, monkeypatch):
        """Test that non-jpg/png files are rejected."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

        dummy_txt = tmp_path / "not_an_image.txt"
        dummy_txt.write_text("Hello")

        response = client.post('/inbound', json={
            'action': 'solve_captcha',
            'params': {
                'image_path': str(dummy_txt)
            }
        })
        assert response.status_code == 200
        job_id = response.get_json()['job_id']
        time.sleep(0.1)

        process_inbound_queue(app, MagicMock(is_set=lambda: False))

        data = poll_for_result(client, job_id)
        assert data is not None
        assert data['status'] == 'Failed'
        assert "Unsupported image format" in data['error']
