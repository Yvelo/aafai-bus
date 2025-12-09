# -*- coding: utf-8 -*-
"""
Unit tests for the drooms_scraping action.
"""

import unittest
from unittest.mock import patch, MagicMock, call
import os
import sys

# Add the src directory to the path to allow importing the action
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from actions import drooms_scraping

class TestDroomsScrapingUnit(unittest.TestCase):

    @patch('actions.drooms_scraping.time.sleep')
    @patch('actions.drooms_scraping.WebDriverWait')
    @patch('actions.drooms_scraping._setup_driver')
    @patch('actions.drooms_scraping._login')
    @patch('actions.drooms_scraping._expand_all_folders')
    @patch('actions.drooms_scraping._gather_all_items')
    @patch('actions.drooms_scraping._process_all_items')
    @patch('actions.drooms_scraping.os.makedirs')
    def test_run_success(self, mock_makedirs, mock_process_all, mock_gather_all, mock_expand_all, mock_login, mock_setup_driver, mock_wait, mock_sleep):
        """
        Test the main 'run' function under ideal, fully mocked conditions.
        """
        # --- Setup Mocks ---
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        mock_gather_all.return_value = [{'id': '1', 'order': '1', 'text': 'Test', 'is_folder': False}]
        
        # Mock the WebDriverWait to return a mock element, satisfying the check after login
        mock_wait.return_value.until.return_value = MagicMock()

        params = {'url': 'http://fake-url.com', 'username': 'user', 'password': 'pw'}
        job_context = {'job_output_dir': os.path.join('tmp', 'job_output')}
        
        # --- Execute ---
        result = drooms_scraping.run(params, job_context)

        # --- Assert ---
        download_root = 'C:/temp/drooms_scraping'
        mock_makedirs.assert_called_once_with(download_root, exist_ok=True)
        mock_setup_driver.assert_called_once()
        mock_login.assert_called_once_with(mock_driver, params['url'], params['username'], params['password'])
        mock_expand_all.assert_called_once_with(mock_driver)
        mock_gather_all.assert_called_once_with(mock_driver)
        mock_process_all.assert_called_once_with(mock_driver, mock_gather_all.return_value, download_root)
        
        mock_driver.quit.assert_called_once()
        self.assertEqual(result['status'], 'complete')

    def test_run_missing_parameters(self):
        """
        Test that 'run' fails gracefully if essential parameters are missing.
        """
        result = drooms_scraping.run({'url': 'http://some-url.com'}, {})
        self.assertEqual(result['status'], 'error')
        self.assertIn('Missing required parameters', result['message'])

    @patch('actions.drooms_scraping._setup_driver')
    @patch('actions.drooms_scraping._login', side_effect=Exception("Login Failed"))
    def test_run_login_failure_handling(self, mock_login, mock_setup_driver):
        """
        Test that 'run' handles exceptions during the login process and cleans up.
        """
        mock_driver = MagicMock()
        mock_setup_driver.return_value = mock_driver
        params = {'url': 'http://fake-url.com', 'username': 'user', 'password': 'pw'}
        
        result = drooms_scraping.run(params, {'job_output_dir': 'tmp/output'})
        
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['message'], 'Login Failed')
        mock_driver.quit.assert_called_once()

    @patch('actions.drooms_scraping.WebDriverWait')
    @patch('actions.drooms_scraping.os.makedirs')
    @patch('actions.drooms_scraping.os.path.exists', return_value=False)
    @patch('actions.drooms_scraping._process_document')
    def test_process_all_items_hierarchy(self, mock_process_doc, mock_exists, mock_makedirs, mock_wait):
        """
        Test that _process_all_items correctly creates a directory structure based on order index.
        """
        mock_driver = MagicMock()
        download_root = os.path.join('tmp', 'test_download')
        
        items = [
            {'id': 'doc1', 'order': '1.1', 'text': '1.1 Document A', 'is_folder': False},
            {'id': 'folder1', 'order': '1', 'text': '1 Folder One', 'is_folder': True},
            {'id': 'folder2', 'order': '1.2', 'text': '1.2 Subfolder B', 'is_folder': True},
            {'id': 'doc2', 'order': '1.2.1', 'text': '1.2.1 Document C', 'is_folder': False},
            {'id': 'doc3', 'order': '2.1', 'text': '2.1 Document D', 'is_folder': False},
            {'id': 'folder3', 'order': '2', 'text': '2 Folder Two', 'is_folder': True},
        ]

        drooms_scraping._process_all_items(mock_driver, items, download_root)

        expected_folder_calls = [
            call(os.path.join(download_root, '1 Folder One'), exist_ok=True),
            call(os.path.join(download_root, '1 Folder One', '1.2 Subfolder B'), exist_ok=True),
            call(os.path.join(download_root, '2 Folder Two'), exist_ok=True),
        ]
        mock_makedirs.assert_has_calls(expected_folder_calls, any_order=True)

        expected_doc_calls = [
            call(mock_driver, os.path.join(download_root, '1 Folder One', '1.1 Document A.pdf')),
            call(mock_driver, os.path.join(download_root, '1 Folder One', '1.2 Subfolder B', '1.2.1 Document C.pdf')),
            call(mock_driver, os.path.join(download_root, '2 Folder Two', '2.1 Document D.pdf')),
        ]
        mock_process_doc.assert_has_calls(expected_doc_calls, any_order=True)

    @patch('actions.drooms_scraping.time.sleep')
    @patch('actions.drooms_scraping.WebDriverWait')
    @patch('actions.drooms_scraping.shutil.rmtree')
    @patch('actions.drooms_scraping.Image.open')
    @patch('actions.drooms_scraping.os.path.exists', return_value=True)
    def test_process_document_pdf_creation(self, mock_exists, mock_image_open, mock_rmtree, mock_wait, mock_sleep):
        """
        Test the _process_document helper to ensure it correctly captures pages and creates a PDF.
        """
        mock_driver = MagicMock()
        mock_viewer = MagicMock()
        
        # Configure the mock for the viewer element returned by WebDriverWait
        mock_wait.return_value.until.return_value = mock_viewer

        mock_page1 = MagicMock()
        mock_page1.get_attribute.return_value = 'page-1'
        # Set the size attribute directly on the mock
        mock_page1.size = {'width': 800, 'height': 1000} 
        
        mock_viewer.find_element.return_value = mock_page1
        mock_viewer.find_elements.side_effect = [[mock_page1], [], [], []]
        
        mock_image = MagicMock()
        mock_image.convert.return_value = mock_image
        mock_image_open.return_value = mock_image
        
        pdf_path = os.path.join('tmp', 'test_doc.pdf')
        
        drooms_scraping._process_document(mock_driver, pdf_path)
        
        self.assertEqual(mock_page1.screenshot.call_count, 1)
        self.assertEqual(mock_image_open.call_count, 1)
        
        mock_image.save.assert_called_once_with(pdf_path, save_all=True, append_images=[])
        
        temp_img_dir = os.path.join(os.path.dirname(pdf_path), "temp_images_" + os.path.basename(pdf_path))
        mock_rmtree.assert_called_once_with(temp_img_dir, ignore_errors=True)

if __name__ == '__main__':
    unittest.main()
