import logging
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

# --- Constants ---
MAXIMUM_DOWNLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Uses a headless browser to navigate to a URL, extract all visible text,
    and return it in the outbound JSON message.
    """
    url = params.get('url')
    if not url:
        # This is a programming error, the scheduler should catch it.
        raise ValueError("'url' parameter is missing for 'full_recursive_download'")

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Set user data and cache directories to be inside the writable download_dir
    user_data_dir = os.path.join(download_dir, "user-data")
    disk_cache_dir = os.path.join(download_dir, "cache")
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_options.add_argument(f"--disk-cache-dir={disk_cache_dir}")

    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        logging.info(f"Navigating to URL: {url}")
        driver.get(url)

        # Extract text from the body of the page
        body_text = driver.find_element(By.TAG_NAME, 'body').text
        logging.info(f"Successfully extracted text from {url}")

        text_bytes = body_text.encode('utf-8')
        text_size = len(text_bytes)
        warning = None

        # Check if the text exceeds the maximum size
        if text_size > MAXIMUM_DOWNLOAD_SIZE:
            warning = f"Text content exceeded {MAXIMUM_DOWNLOAD_SIZE} bytes and was truncated."
            logging.warning(f"For job {job_id}, {warning}")
            # Truncate the text to the maximum allowed size
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
            driver.quit()

    write_result_to_outbound(job_id, result)