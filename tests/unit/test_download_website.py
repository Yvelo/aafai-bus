import unittest
from unittest.mock import MagicMock, patch
import os
import tempfile
import shutil
from actions.drooms_scraping import execute

class TestDownloadWebsite(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.job_id = "test_job_123"
        self.params = {
            "url": "http://example.com",
            "username": "testuser",
            "password": "testpassword"
        }
        self.write_result_to_outbound = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @patch('actions.drooms_scraping._setup_driver')
    @patch('actions.drooms_scraping._login')
    @patch('actions.drooms_scraping._expand_all_folders')
    @patch('actions.drooms_scraping._gather_all_items')
    @patch('actions.drooms_scraping._process_all_items')
    def test_execute_success(self, mock_process_all_items, mock_gather_all_items, mock_expand_all_folders, mock_login, mock_setup_driver):
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_gather_all_items.return_value = [{"id": "doc1", "order": "1", "text": "Doc 1", "is_folder": False}]

        execute(self.job_id, self.params, self.test_dir, self.write_result_to_outbound)

        mock_setup_driver.assert_called_once_with(headless=True)
        mock_login.assert_called_once_with(mock_driver, self.params["url"], self.params["username"], self.params["password"])
        mock_expand_all_folders.assert_called_once()
        mock_gather_all_items.assert_called_once()
        mock_process_all_items.assert_called_once()

        self.write_result_to_outbound.assert_called_once()
        args, _ = self.write_result_to_outbound.call_args
        self.assertEqual(args[0], self.job_id)
        self.assertEqual(args[1]['status'], 'complete')

    def test_missing_parameters(self):
        execute(self.job_id, {"url": "http://example.com"}, self.test_dir, self.write_result_to_outbound)
        self.write_result_to_outbound.assert_called_once()
        args, _ = self.write_result_to_outbound.call_args
        self.assertEqual(args[1]['status'], 'error')
        self.assertIn("Missing required parameters", args[1]['message'])

if __name__ == '__main__':
    unittest.main()
