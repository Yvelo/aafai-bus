import logging
import os
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import tempfile


def _setup_driver(job_download_dir):
    """Configures and returns a headless Chrome WebDriver instance."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-crash-reporter")

    # Create a single, persistent temporary directory for this driver instance.
    # This directory will serve as the HOME directory for the Chrome process.
    temp_dir = tempfile.mkdtemp()

    # **CRITICAL FIX**: Set the HOME environment variable for the Chrome process.
    # This forces Chrome to write user-specific files (like .local) here,
    # avoiding permission errors in /var/www.
    os.environ['HOME'] = temp_dir

    # Define paths within our new temporary HOME directory
    user_data_dir = os.path.join(temp_dir, "user-data")
    disk_cache_dir = os.path.join(temp_dir, "cache")
    crash_dumps_dir = os.path.join(temp_dir, "crash-dumps")

    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_options.add_argument(f"--disk-cache-dir={disk_cache_dir}")
    chrome_options.add_argument(f"--crash-dumps-dir={crash_dumps_dir}")

    # Isolate Selenium Manager's driver cache
    selenium_manager_cache_dir = os.path.join(job_download_dir, "selenium_manager_cache")
    os.makedirs(selenium_manager_cache_dir, exist_ok=True)
    os.environ['SE_CACHE_PATH'] = selenium_manager_cache_dir

    # Enable verbose logging for chromedriver
    chromedriver_log_path = os.path.join(job_download_dir, "chromedriver.log")
    service = Service(service_args=['--verbose', f'--log-path={chromedriver_log_path}'])

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)

    # Store the temporary directory path so it can be cleaned up later
    driver.temp_dir = temp_dir

    return driver


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Uses a headless browser to navigate to a URL, extract all visible text,
    and return it in the outbound JSON message.
    """
    url = params.get('url')
    if not url:
        raise ValueError("'url' parameter is missing for 'full_recursive_download'")

    # Create a job-specific directory to avoid conflicts
    job_download_dir = os.path.join(download_dir, job_id)
    os.makedirs(job_download_dir, exist_ok=True)

    driver = None
    try:
        driver = _setup_driver(job_download_dir)

        logging.info(f"Navigating to URL: {url}")
        driver.get(url)

        body_text = driver.find_element(By.TAG_NAME, 'body').text
        logging.info(f"Successfully extracted text from {url}")

        text_bytes = body_text.encode('utf-8')
        text_size = len(text_bytes)
        warning = None

        if text_size > MAXIMUM_DOWNLOAD_SIZE:
            warning = f"Text content exceeded {MAXIMUM_DOWNLOAD_SIZE} bytes and was truncated."
            logging.warning(f"For job {job_id}, {warning}")
            body_text = text_bytes[:MAXIMUM_DOWNLOAD_SIZE].decode('utf-8', errors='ignore')

        result = {
            'job_id': job_id,
            'status': 'complete',
            'result': {
                'text': body_text,
                'size_bytes': text_size,
                'warning': warning
            }
        }

    except Exception as e:
        logging.error(f"An error occurred during Selenium execution for job {job_id}: {e}", exc_info=True)
        result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}

    finally:
        if driver:
            # Clean up the temporary directory
            if hasattr(driver, 'temp_dir'):
                shutil.rmtree(driver.temp_dir)
            driver.quit()
        # It's still a good practice to clean up the job-specific directory.
        # However, it's commented out in the original script, so we'll respect that.
        # shutil.rmtree(job_download_dir)

    write_result_to_outbound(job_id, result)


if __name__ == '__main__':
    # This block allows the script to be run directly for testing purposes.
    # Example: python your_script_name.py "https://www.google.com"
    import sys
    import uuid
    import json

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    if len(sys.argv) < 2:
        print("Usage: python your_script_name.py <URL>")
        sys.exit(1)

    test_url = sys.argv[1]
    test_job_id = f"test-job-{uuid.uuid4()}"
    test_params = {'url': test_url}

    # Use a standard temporary directory for test output
    test_download_dir = tempfile.gettempdir()


    def print_result_to_console(job_id, result):
        """A mock writer function that prints the result to the console."""
        print(json.dumps(result, indent=2))


    execute(test_job_id, test_params, test_download_dir, print_result_to_console)