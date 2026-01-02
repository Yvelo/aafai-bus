import logging
import os
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import tempfile
from urllib.parse import urlparse, urljoin, urlunparse
from collections import deque
import time # Import the time module
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth
from webdriver_manager.core.driver_cache import DriverCacheManager


MAXIMUM_DOWNLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
DEFAULT_MAX_DEPTH = 1 # Default maximum recursion depth


def _setup_driver(job_download_dir):
    """Configures and returns a headless Chrome WebDriver instance."""
    chrome_options = Options()
    if os.environ.get('HEADLESS_BROWSER', 'true').lower() == 'true':
        chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-crash-reporter")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-in-process-stack-traces")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--disable-dev-tools")
    chrome_options.add_argument("--window-size=1920,1080") # Set a consistent window size

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

    # Use a persistent cache for WebDriver Manager
    persistent_cache_dir = os.path.join(os.path.expanduser("~"), ".aafai-bus-cache", "drivers")
    os.makedirs(persistent_cache_dir, exist_ok=True)

    # Enable verbose logging for chromedriver
    chromedriver_log_path = os.path.join(job_download_dir, "chromedriver.log")
    service = Service(ChromeDriverManager(cache_manager=DriverCacheManager(root_dir=persistent_cache_dir)).install(), service_args=['--verbose', f'--log-path={chromedriver_log_path}'])

    driver = webdriver.Chrome(service=service, options=chrome_options)

    # --- Apply selenium-stealth ---
    # This function applies a series of patches to the driver to make it
    # appear more like a regular user's browser, helping to bypass bot detection.
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )

    driver.set_page_load_timeout(60)

    # Store the temporary directory path so it can be cleaned up later
    driver.temp_dir = temp_dir

    return driver, service

def _normalize_domain(domain):
    """Removes 'www.' from the beginning of a domain for consistent comparison."""
    if domain.startswith('www.'):
        return domain[4:]
    return domain

def _canonicalize_url(url):
    """
    Canonicalizes a URL by removing fragments and normalizing trailing slashes in the path.
    """
    parsed_url = urlparse(url)
    
    # Remove fragment
    parsed_url_no_fragment = parsed_url._replace(fragment='')
    
    # Normalize path: remove trailing slash unless it's the root path
    clean_path = parsed_url_no_fragment.path
    if clean_path.endswith('/') and len(clean_path) > 1:
        clean_path = clean_path.rstrip('/')
    elif not clean_path: # Empty path should be '/'
        clean_path = '/'
    
    return urlunparse(parsed_url_no_fragment._replace(path=clean_path))


def _get_links_from_page(driver, current_page_url, initial_domain, current_depth, max_depth, visited_urls, queued_urls):
    """
    Extracts all valid, same-domain links from the current page,
    filters out already visited or queued URLs, and returns them with an incremented depth.
    """
    links_to_add = []

    if current_depth >= max_depth:
        return []

    normalized_initial_domain = _normalize_domain(initial_domain)

    try:
        a_tags = driver.find_elements(By.TAG_NAME, 'a')
        for a_tag in a_tags:
            href = a_tag.get_attribute('href')
            if href:
                # Resolve relative URLs to absolute URLs using the current page's URL
                absolute_url = urljoin(current_page_url, href)
                
                # Canonicalize the absolute URL
                clean_url = _canonicalize_url(absolute_url)
                parsed_clean_url = urlparse(clean_url)

                # Only consider http/https links
                if parsed_clean_url.scheme not in ['http', 'https']:
                    continue

                # Ensure it's the same domain as the initial URL (after normalization)
                if _normalize_domain(parsed_clean_url.netloc) == normalized_initial_domain:
                    # Only add if not already successfully crawled AND not already in the queue
                    if clean_url not in visited_urls and clean_url not in queued_urls:
                        links_to_add.append((clean_url, current_depth + 1))
    except Exception as e:
        logging.warning(f"Error extracting links from {driver.current_url}: {e}")

    return links_to_add


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Uses a headless browser to recursively navigate to a URL, extract all visible text
    from linked pages within the same domain up to a certain depth,
    and return it in the outbound JSON message.
    """
    initial_url = params.get('url')
    if not initial_url:
        raise ValueError("'url' parameter is missing for 'full_recursive_download'")

    # Ensure the URL has a scheme.
    if not urlparse(initial_url).scheme:
        initial_url = 'https://' + initial_url

    # Canonicalize the initial URL
    initial_url = _canonicalize_url(initial_url)

    max_depth = params.get('max_depth', DEFAULT_MAX_DEPTH)

    # Create a job-specific directory to avoid conflicts
    job_download_dir = os.path.join(download_dir, job_id)
    os.makedirs(job_download_dir, exist_ok=True)

    driver = None
    service = None
    crawled_data = []
    visited_urls = set() # Stores URLs that have been successfully crawled and their content extracted
    urls_to_visit = deque([(initial_url, 0)]) # (url, depth) - Queue of URLs to visit
    queued_urls = {initial_url} # Stores URLs that are currently in urls_to_visit or have been added to it

    # Extract the domain of the initial URL once (from the canonicalized initial_url)
    initial_domain = urlparse(initial_url).netloc

    try:
        driver, service = _setup_driver(job_download_dir)

        while urls_to_visit:
            current_url, current_depth = urls_to_visit.popleft()
            
            # Use discard instead of remove to prevent KeyError if URL is somehow not in queued_urls
            queued_urls.discard(current_url) 

            if current_url in visited_urls: # If this URL has already been successfully crawled, skip
                logging.info(f"Skipping already crawled URL: {current_url}")
                continue

            logging.info(f"Crawling URL: {current_url} (Depth: {current_depth})")

            try:
                driver.get(current_url)
                body_text = driver.find_element(By.TAG_NAME, 'body').text
                logging.info(f"Successfully extracted text from {current_url}")

                text_bytes = body_text.encode('utf-8')
                text_size = len(text_bytes)
                warning = None

                if text_size > MAXIMUM_DOWNLOAD_SIZE:
                    warning = f"Text content exceeded {MAXIMUM_DOWNLOAD_SIZE} bytes and was truncated."
                    logging.warning(f"For job {job_id}, {warning}")
                    body_text = text_bytes[:MAXIMUM_DOWNLOAD_SIZE].decode('utf-8', errors='ignore')

                crawled_data.append({
                    'url': current_url,
                    'text': body_text,
                    'size_bytes': text_size,
                    'warning': warning
                })
                visited_urls.add(current_url) # Mark as successfully crawled

                # Extract new links to visit, passing the current_url, initial_domain, and both sets
                new_links = _get_links_from_page(driver, current_url, initial_domain, current_depth, max_depth, visited_urls, queued_urls)
                for link, depth in new_links:
                    urls_to_visit.append((link, depth))
                    queued_urls.add(link) # Add to queued_urls to prevent future duplicates

            except Exception as e:
                logging.error(f"Error crawling {current_url} for job {job_id}: {e}", exc_info=True)
                crawled_data.append({
                    'url': current_url,
                    'text': '',
                    'size_bytes': 0,
                    'error': str(e)
                })
                # Do not add to visited_urls if there was an error, so it might be retried if discovered again.


        result = {
            'job_id': job_id,
            'status': 'complete',
            'result': {
                'crawled_pages': crawled_data,
                'total_pages_crawled': len(crawled_data)
            }
        }

    except Exception as e:
        logging.error(f"An error occurred during Selenium execution for job {job_id}: {e}", exc_info=True)
        result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}

    finally:
        if driver:
            driver.quit()
        if service:
            service.stop()
        # Add a small delay to allow processes to release file handles
        time.sleep(1)
        # Clean up the temporary directory
        if driver and hasattr(driver, 'temp_dir'):
            try:
                shutil.rmtree(driver.temp_dir)
            except OSError as e:
                logging.warning(f"Could not remove temporary directory {driver.temp_dir}: {e}")

    write_result_to_outbound(job_id, result)


if __name__ == '__main__':
    # This block allows the script to be run directly for testing purposes.
    # Example: python your_script_name.py "https://www.google.com"
    import sys
    import uuid
    import json

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    if len(sys.argv) < 2:
        print("Usage: python your_script_name.py <URL> [max_depth]")
        sys.exit(1)

    test_url = sys.argv[1]
    test_max_depth = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MAX_DEPTH
    test_job_id = f"test-job-{uuid.uuid4()}"
    test_params = {'url': test_url, 'max_depth': test_max_depth}

    # Use a standard temporary directory for test output
    test_download_dir = tempfile.gettempdir()


    def print_result_to_console(job_id, result):
        """A mock writer function that prints the result to the console."""
        print(json.dumps(result, indent=2))


    execute(test_job_id, test_params, test_download_dir, print_result_to_console)
