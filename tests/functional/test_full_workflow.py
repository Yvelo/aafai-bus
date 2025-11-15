import json
from unittest.mock import patch, mock_open


# Correct patch paths targeting the 'server' module
@patch('server.open', new_callable=mock_open)
@patch('server.json.dump')
def test_receive_task_file_writing(mock_json_dump, mock_file_open, client):
    """Test that the receive_task function writes a file."""

    task_data = {'action': 'test_action'}

    response = client.post('/inbound',
                           data=json.dumps(task_data),
                           content_type='application/json')

    assert response.status_code == 200

    # Assert that the mocks were called
    mock_file_open.assert_called_once()
    mock_json_dump.assert_called_once()