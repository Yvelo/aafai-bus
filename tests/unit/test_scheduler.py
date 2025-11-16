import os
import json
from unittest.mock import patch
from server import process_inbound_queue

def test_process_inbound_queue_malformed_json(app):
    """
    Tests that the scheduler correctly handles a task file that is not valid JSON.
    """
    # 1. ARRANGE
    base_path = app.config['BASE_QUEUE_PATH']
    inbound_dir = os.path.join(base_path, 'inbound')
    failed_dir = os.path.join(base_path, 'failed')
    malformed_filename = "malformed_task.json"
    malformed_filepath = os.path.join(inbound_dir, malformed_filename)

    with open(malformed_filepath, 'w') as f:
        f.write("{'invalid_json': True,}")

    # 2. ACT
    with patch('server.write_result_to_outbound') as mock_write_result:
        process_inbound_queue(app)

    # 3. ASSERT
    assert not os.path.exists(malformed_filepath)
    assert os.path.exists(os.path.join(failed_dir, malformed_filename))

    mock_write_result.assert_called_once()
    result_data = mock_write_result.call_args[0][1]
    assert result_data['status'] == 'failed'
    # Check for a substring of the JSON error, which is more robust
    assert 'Expecting property name' in result_data['error']


def test_process_inbound_queue_unknown_action(app):
    """
    Tests that the scheduler handles a task with an action that does not exist.
    """
    # 1. ARRANGE
    base_path = app.config['BASE_QUEUE_PATH']
    inbound_dir = os.path.join(base_path, 'inbound')
    failed_dir = os.path.join(base_path, 'failed')
    job_id = "test-unknown-action"
    task_filename = f"12345_{job_id}.json"
    task_filepath = os.path.join(inbound_dir, task_filename)

    task_data = {'job_id': job_id, 'action': 'non_existent_action', 'params': {}}
    with open(task_filepath, 'w') as f:
        json.dump(task_data, f)

    # 2. ACT
    with patch('server.write_result_to_outbound') as mock_write_result:
        process_inbound_queue(app)

    # 3. ASSERT
    assert not os.path.exists(task_filepath)
    assert os.path.exists(os.path.join(failed_dir, task_filename))

    mock_write_result.assert_called_once()
    result_data = mock_write_result.call_args[0][1]
    assert result_data['status'] == 'failed'
    # Check for the specific error message raised by the scheduler
    assert "Action 'non_existent_action' not found" in result_data['error']
