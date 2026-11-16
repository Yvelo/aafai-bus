from unittest.mock import MagicMock, patch

import pytest

from src.actions.solve_captcha import solve_captcha


@pytest.mark.parametrize("model, expected", [
    (None, "gemini-2.5-flash"),
    ("custom-model", "custom-model"),
])
def test_captcha_uses_expected_gemini_model(tmp_path, monkeypatch, model, expected):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    image = tmp_path / "captcha.png"
    image.write_bytes(b"image")
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"matrix": [[true]]}'}]}}]
    }

    with patch("src.actions.gemini_prompt.requests.post", return_value=response) as post:
        assert solve_captcha(str(image), model=model)["matrix"] == [[True]]

    assert f"/models/{expected}:generateContent?key=test-key" in post.call_args.args[0]
    assert post.call_args.kwargs["json"]["generationConfig"]["responseMimeType"] == "application/json"