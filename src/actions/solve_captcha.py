import os
import json
import logging
from src.actions.gemini_prompt import call_gemini_api

CAPTCHA_PROMPT = """You are analyzing an image CAPTCHA puzzle (such as reCAPTCHA or hCaptcha tile selection).
Analyze the grid in the provided image.
Identify the grid dimensions (rows x columns, e.g. 3x3 or 4x4).
Look at what the CAPTCHA prompt asks to select (e.g. motorcycles, crosswalks, traffic lights, cars, bicycles, hydrants).
If no explicit instruction is found inside the image, identify tiles containing the prominent target objects.
For each cell in the grid, determine whether that tile contains the target or matches the required selection criteria.
Return ONLY a valid JSON object matching this schema:
{
  "rows": <number of rows>,
  "cols": <number of columns>,
  "target": "<description of what is being selected>",
  "matrix": [
    [true, false, false],
    [false, true, false],
    [false, false, true]
  ]
}
Each element of 'matrix' must be a boolean (true or false). The dimension of 'matrix' must be rows x cols.
Do not output markdown code blocks or explanations, only valid JSON."""


def solve_captcha(image_path, model=None, prompt=None):
    """
    Solves an image captcha (JPG or PNG) by calling Gemini with multimodal input.
    Returns a dict containing 'matrix' (list of list of booleans), 'rows', 'cols', etc.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    ext = os.path.splitext(image_path)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png']:
        raise ValueError(f"Unsupported image format: {ext}. Only JPG and PNG are supported.")

    effective_prompt = prompt or CAPTCHA_PROMPT
    result = call_gemini_api(
        prompt=effective_prompt,
        files=[image_path],
        json_output=True,
        model=model
    )

    # Normalize result
    if isinstance(result, str):
        result = json.loads(result)

    if not isinstance(result, dict) or "matrix" not in result:
        raise ValueError(f"Unexpected response structure from Gemini: {result}")

    # Ensure matrix values are booleans
    matrix = result.get("matrix", [])
    bool_matrix = []
    for row in matrix:
        bool_matrix.append([bool(cell) for cell in row])
    result["matrix"] = bool_matrix
    result["rows"] = len(bool_matrix)
    result["cols"] = len(bool_matrix[0]) if bool_matrix else 0

    return result


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Executes the solve_captcha action.
    Params:
      - image_path (str): Absolute or relative path to a jpg or png captcha image.
      - model (str, optional): Gemini model to use.
      - prompt (str, optional): Custom prompt instructions if any.
    """
    try:
        image_path = params.get("image_path")
        if not image_path:
            raise ValueError("Parameter 'image_path' is required.")

        model = params.get("model")
        custom_prompt = params.get("prompt")

        logging.info(f"Solving captcha for job {job_id} using image: {image_path}")
        captcha_result = solve_captcha(image_path, model=model, prompt=custom_prompt)

        result_data = {
            "job_id": job_id,
            "status": "Completed",
            "result": captcha_result
        }
        write_result_to_outbound(job_id, result_data)

    except Exception as e:
        logging.error(f"Error executing solve_captcha action for job {job_id}: {e}")
        error_result = {
            "job_id": job_id,
            "status": "Failed",
            "error": str(e)
        }
        write_result_to_outbound(job_id, error_result)
