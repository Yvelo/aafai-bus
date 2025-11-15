#tests/unit/test_outbound_api.py
import json
import os
import uuid

def test_check_task_status_success(client, app):
    """
    Test the /outbound endpoint for a successfully completed job.
    This test requires manually creating a result file for the client to retrieve.
    """
    # 1. Setup: Create a fake result file in the outbound queue directory
    job_id = str(uuid.uuid4())
    expected_result = {
        'job_id': job_id,
        'status': 'complete',
        'result': 'The process finished successfully.'
    }

    # Use the app's config to get the correct, temporary test queue path
    base_path = app.config['BASE_QUEUE_PATH']
    outbound_dir = os.path.join(base_path, 'outbound')
    consumed_dir = os.path.join(base_path, 'consumed')
    result_filepath = os.path.join(outbound_dir, f"{job_id}.json")

    # The conftest fixture already creates the 'outbound' directory
    with open(result_filepath, 'w') as f:
        json.dump(expected_result, f)

    # 2. Action: Make a request to the outbound endpoint to fetch the result
    response = client.get(f'/outbound?job_id={job_id}')

    # 3. Assertions: Verify the response and the side-effects
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data == expected_result

    # Verify that the result file was moved from outbound to consumed
    assert not os.path.exists(result_filepath)
    consumed_filepath = os.path.join(consumed_dir, f"result_{job_id}.json")
    assert os.path.exists(consumed_filepath)


def test_check_task_status_pending(client):
    """
    Test the /outbound endpoint for a job that is still pending (no result file).
    """
    # 1. Setup: Choose a job_id that is guaranteed not to exist
    non_existent_job_id = "job_that_does_not_exist"

    # 2. Action: Poll the endpoint for this job ID
    response = client.get(f'/outbound?job_id={non_existent_job_id}')

    # 3. Assertions: Verify the status is 'pending'
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'pending'
    assert 'message' in data


def test_check_task_status_missing_job_id(client):
    """
    Test the /outbound endpoint for a request missing the job_id parameter.
    """
    # 1. Action: Make a request without the job_id query parameter
    response = client.get('/outbound')

    # 2. Assertions: Verify that the server returns a 400 Bad Request error
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data['status'] == 'error'
    assert 'Job ID is required' in data['message']