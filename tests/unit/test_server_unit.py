import json
from unittest.mock import patch, mock_open

@patch('os.path.exists')
@patch('os.listdir')
@patch('builtins.open', new_callable=mock_open, read_data=json.dumps({'id': 'test_msg'}))
def test_get_all_messages_with_data(mock_file, mock_listdir, mock_exists, client):
    """Unit test for get_all_messages with mocked filesystem."""
    mock_exists.return_value = True
    mock_listdir.return_value = ['message.json']

    response = client.get('/messages')
    assert response.status_code == 200
    data = response.get_json()

    stages = ['inbound', 'outbound', 'consumed', 'failed', 'processing']
    for stage in stages:
        assert len(data[stage]) == 1
        assert data[stage][0]['id'] == 'test_msg'
        assert data[stage][0]['filename'] == 'message.json'

@patch('os.path.exists')
@patch('os.listdir')
@patch('os.path.isfile')
@patch('os.path.islink')
@patch('os.path.isdir')
@patch('os.unlink')
@patch('shutil.rmtree')
def test_clear_all_messages(mock_rmtree, mock_unlink, mock_isdir, mock_islink, mock_isfile, mock_listdir, mock_exists, client):
    """Unit test for clear_all_messages with mocked filesystem."""
    mock_exists.return_value = True
    mock_listdir.side_effect = [
        ['file1.json', 'dir1'],  # inbound
        ['file2.json'],          # outbound
        [],                      # consumed
        ['file3.json'],          # failed
        ['file4.json']           # processing
    ]
    
    def isdir_side_effect(path):
        return 'dir' in path

    def isfile_side_effect(path):
        return 'file' in path

    mock_isdir.side_effect = isdir_side_effect
    mock_islink.return_value = False
    mock_isfile.side_effect = isfile_side_effect

    response = client.post('/messages/clear')

    assert response.status_code == 200
    data = response.get_json()

    assert data['status'] == 'success'
    assert data['cleared_messages']['inbound'] == 2
    assert data['cleared_messages']['outbound'] == 1
    assert data['cleared_messages']['consumed'] == 0
    assert data['cleared_messages']['failed'] == 1
    assert data['cleared_messages']['processing'] == 1
    
    assert mock_unlink.call_count == 4
    assert mock_rmtree.call_count == 1
