# -*- coding: utf-8 -*-
"""
Unit tests for the drooms_scraping action.
"""

import unittest
from unittest.mock import patch, MagicMock, call
import os

# It's good practice to add the src directory to the path for testing
# This ensures that the test runner can find the module to be tested.
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from actions import drooms_scraping

class TestDroomsScrapingUnit(unittest.TestCase):

    @patch('actions.drooms_scraping.os.path.exists', return_value=True)
    @patch('actions.drooms_scraping.shutil.rmtree')
    @patch('actions.drooms_scraping.webdriver.Chrome')
    @patch('actions.drooms_scraping._login')
    @patch('actions.drooms_scraping._process_folder')
    @patch('actions.drooms_scraping.os.makedirs')
    def test_run_success(self, mock_makedirs, mock_process_folder, mock_login, mock_chrome, mock_rmtree, mock_exists):
        """
        Test the main 'run' function under ideal conditions.
        """
        # --- Setup Mocks ---
        mock_driver = MagicMock()
        mock_chrome.return_value = mock_driver
        
        params = {
            'url': 'http://fake-drooms-url.com',
            'username': 'testuser',
            'password': 'testpassword'
        }
        # Use os.path.join to be platform-agnostic
        job_output_dir = os.path.join('tmp', 'fake_job_output')
        job_context = {'job_output_dir': job_output_dir}
        
        # --- Execute ---
        result = drooms_scraping.run(params, job_context)

        # --- Assert ---
        # Use os.path.join for the expected path
        expected_download_root = os.path.join(job_output_dir, 'drooms_download')
        mock_makedirs.assert_any_call(expected_download_root, exist_ok=True)
        
        mock_chrome.assert_called_once()
        mock_login.assert_called_once_with(mock_driver, params['url'], params['username'], params['password'])
        mock_process_folder.assert_called_once_with(mock_driver, expected_download_root, [])
        
        mock_driver.quit.assert_called_once()
        temp_driver_dir = os.path.join(job_output_dir, 'driver_temp')
        # Ensure os.path.exists was checked before rmtree
        mock_exists.assert_called_with(temp_driver_dir)
        mock_rmtree.assert_called_with(temp_driver_dir)

        self.assertEqual(result['status'], 'complete')
        # Corrected assertion to match the actual success message
        self.assertIn('D-Rooms scraping completed', result['message'])

    def test_run_missing_parameters(self):
        """
        Test that 'run' fails gracefully if parameters are missing.
        """
        params = {'url': 'http://some-url.com'}
        job_context = {'job_output_dir': os.path.join('tmp', 'fake_dir')}
        
        result = drooms_scraping.run(params, job_context)
        
        self.assertEqual(result['status'], 'error')
        self.assertIn('Missing required parameters', result['message'])

    @patch('actions.drooms_scraping.os.path.exists', return_value=True)
    @patch('actions.drooms_scraping.shutil.rmtree')
    @patch('actions.drooms_scraping.webdriver.Chrome')
    @patch('actions.drooms_scraping._login', side_effect=Exception("Login Failed"))
    @patch('actions.drooms_scraping.os.makedirs')
    def test_run_login_failure(self, mock_makedirs, mock_login, mock_chrome, mock_rmtree, mock_exists):
        """
        Test that 'run' handles exceptions during the login process.
        """
        mock_driver = MagicMock()
        mock_chrome.return_value = mock_driver
        
        params = {
            'url': 'http://fake-drooms-url.com',
            'username': 'testuser',
            'password': 'testpassword'
        }
        job_output_dir = os.path.join('tmp', 'fake_job_output')
        job_context = {'job_output_dir': job_output_dir}
        
        result = drooms_scraping.run(params, job_context)
        
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['message'], 'Login Failed')
        
        mock_driver.quit.assert_called_once()
        # Check that the cleanup path exists and rmtree is called
        temp_driver_dir = os.path.join(job_output_dir, 'driver_temp')
        mock_exists.assert_called_with(temp_driver_dir)
        mock_rmtree.assert_called_with(temp_driver_dir)

    @patch('actions.drooms_scraping.shutil.rmtree')
    @patch('actions.drooms_scraping.Image.open')
    @patch('actions.drooms_scraping.os.path.exists', return_value=True)
    def test_process_document_creates_pdf(self, mock_exists, mock_image_open, mock_rmtree):
        """
        Test the _process_document helper to ensure it creates a PDF from images.
        """
        # --- Setup Mocks ---
        mock_driver = MagicMock()
        mock_viewer = MagicMock()
        
        # Corrected side_effect: provide enough values for all calls in the loop.
        # The loop runs twice, and each loop calls execute_script twice.
        # The final call to get scroll top breaks the loop.
        mock_driver.execute_script.side_effect = [
            0,      # Call 1: Get scroll top (start of loop 1)
            None,   # Call 2: Scroll down (end of loop 1)
            1080,   # Call 3: Get scroll top (start of loop 2)
            None,   # Call 4: Scroll down (end of loop 2)
            1080,   # Call 5: Get scroll top (start of loop 3, loop breaks)
        ]
        
        mock_driver.find_element.return_value = mock_viewer
        
        mock_image = MagicMock()
        mock_image_open.return_value = mock_image
        
        pdf_path = os.path.join('tmp', 'fake_doc.pdf')
        
        # --- Execute ---
        drooms_scraping._process_document(mock_driver, pdf_path)
        
        # --- Assert ---
        self.assertEqual(mock_viewer.screenshot.call_count, 2)
        self.assertEqual(mock_image_open.call_count, 2)
        mock_image.save.assert_called_once_with(pdf_path, save_all=True, append_images=[mock_image])
        
        # Check that temp image directory is cleaned up
        temp_img_dir = os.path.join(os.path.dirname(pdf_path), "temp_images")
        mock_exists.assert_called_with(temp_img_dir)
        mock_rmtree.assert_called_with(temp_img_dir)


if __name__ == '__main__':
    unittest.main()
