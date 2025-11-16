import json
import os
from unittest.mock import patch

def test_receive_task_file_writing(client, app):
    """
    Test that the receive_task function writes the correct task file,
    ignoring other file operations like the timestamp update.
    """
    task_data = {'action': 'test_action', 'params': {'foo': 'bar'}}

    # Use a patch to inspect the calls to json.dump
    with patch('src.server.json.dump') as mock_json_dump:
        response = client.post('/inbound',
                               data=json.dumps(task_data),
                               content_type='application/json')

    assert response.status_code == 200
    response_data = json.loads(response.data)
    job_id = response_data.get('job_id')
    assert job_id is not None

    # Construct the expected path for the task file using os.path.join for OS compatibility
    base_path = app.config['BASE_QUEUE_PATH']
    inbound_dir = os.path.join(base_path, 'inbound')

    # Find the call to json.dump that wrote the task file
    task_dump_call = None
    for call in mock_json_dump.call_args_list:
        # The second argument to dump is the file handle
        file_handle = call.args[1]
        # The file handle's name attribute contains the full path
        if file_handle.name.startswith(inbound_dir) and file_handle.name.endswith(f"{job_id}.json"):
            task_dump_call = call
            break
    
    assert task_dump_call is not None, f"json.dump was not called for a task file in '{inbound_dir}'"

    # Check the content that was passed to json.dump
    dumped_data = task_dump_call.args[0]
    assert dumped_data['action'] == 'test_action'
    assert dumped_data['job_id'] == job_id
    assert dumped_data['params'] == {'foo': 'bar'}
    assert 'received_at' in dumped_data
