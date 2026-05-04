import logging
import os
import shutil
from selenium import webdriver
from selenium.common import ElementClickInterceptedException, NoSuchElementException, TimeoutException, \
    StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from src.browser_config import get_chrome_options
from selenium.webdriver.chrome.service import Service
import tempfile
from urllib.parse import urlparse, urljoin, urlunparse
from collections import deque
import time
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth
from webdriver_manager.core.driver_cache import DriverCacheManager

MAXIMUM_DOWNLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
DEFAULT_MAX_DEPTH = 1  # Default maximum recursion depth

def _setup_driver(job_download_dir):
    """Configures and returns a headless Chrome WebDriver instance."""
    chrome_options = get_chrome_options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-crash-reporter")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-in-process-stack-traces")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--disable-dev-tools")
    chrome_options.add_argument("--window-size=1920,1080")

    temp_dir = tempfile.mkdtemp()
    os.environ['HOME'] = temp_dir

    user_data_dir = os.path.join(temp_dir, "user-data")
    disk_cache_dir = os.path.join(temp_dir, "cache")
    crash_dumps_dir = os.path.join(temp_dir, "crash-dumps")

    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_options.add_argument(f"--disk-cache-dir={disk_cache_dir}")
    chrome_options.add_argument(f"--crash-dumps-dir={crash_dumps_dir}")

    persistent_cache_dir = os.path.join(os.path.expanduser("~"), ".aafai-bus-cache", "drivers")
    os.makedirs(persistent_cache_dir, exist_ok=True)

    chromedriver_log_path = os.path.join(job_download_dir, "chromedriver.log")
    service = Service(ChromeDriverManager(cache_manager=DriverCacheManager(root_dir=persistent_cache_dir)).install(),
                      service_args=['--verbose', f'--log-path={chromedriver_log_path}'])

    driver = webdriver.Chrome(service=service, options=chrome_options)

    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )

    driver.set_page_load_timeout(60)
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
    parsed_url_no_fragment = parsed_url._replace(fragment='')
    clean_path = parsed_url_no_fragment.path
    if clean_path.endswith('/') and len(clean_path) > 1:
        clean_path = clean_path.rstrip('/')
    elif not clean_path:
        clean_path = '/'
    return urlunparse(parsed_url_no_fragment._replace(path=clean_path))

def _get_links_from_page(driver, current_page_url, initial_domain, current_depth, max_depth, visited_urls, queued_urls):
    """
    Extracts all valid, same-domain links from the current page.
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
                absolute_url = urljoin(current_page_url, href)
                clean_url = _canonicalize_url(absolute_url)
                parsed_clean_url = urlparse(clean_url)

                if parsed_clean_url.scheme not in ['http', 'https']:
                    continue

                if _normalize_domain(parsed_clean_url.netloc) == normalized_initial_domain:
                    if clean_url not in visited_urls and clean_url not in queued_urls:
                        links_to_add.append((clean_url, current_depth + 1))
    except Exception as e:
        logging.warning(f"Error extracting links from {driver.current_url}: {e}")

    return links_to_add

def _click_more_button(driver, button_text):
    """
    Continuously clicks a 'more content' button until it's no longer present or clickable.
    """
    if not button_text:
        return

    logging.info(f"Trying to click the more content button with text: '{button_text}'")

    while True:
        try:
            wait = WebDriverWait(driver, 10)
            # More flexible XPath to find the button by its text, including nested elements
            xpath = f"//button[.//span[contains(text(), '{button_text}')] or @aria-label='{button_text}']"
            button_to_click = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))

            if button_to_click:
                logging.info(f"Clicking button with text: '{button_text}'")
                driver.execute_script("arguments[0].scrollIntoView(true);", button_to_click)
                time.sleep(0.5)
                button_to_click.click()
                time.sleep(2)
            else:
                logging.info(f"More content button with text '{button_text}' not found or no longer interactive.")
                break

        except StaleElementReferenceException:
            logging.warning("StaleElementReferenceException caught. Retrying to find and click the button.")
            continue
        except TimeoutException:
            logging.info(f"More content button with text '{button_text}' not found or no longer interactive.")
            break
        except ElementClickInterceptedException:
            logging.warning("Button click intercepted. Trying to click with JavaScript.")
            try:
                driver.execute_script("arguments[0].click();", button_to_click)
                time.sleep(2)
            except Exception as js_e:
                logging.error(f"JavaScript click also failed: {js_e}")
                break
        except Exception as e:
            logging.error(f"Error clicking 'more' button: {e}")
            break

def _find_next_page_link(driver):
    """
    Finds the 'Next' page link using common heuristics.
    """
    # Scroll to the bottom to ensure pagination links are loaded
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(1) # Give some time for elements to load after scroll

    xpaths = [
        "//a[.//span[@aria-label='Next']]",  # Specific for the biopark site
        "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')]", # "Next" in various cases
        "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'suivant')]", # "Suivant" (French for Next)
        "//a[@aria-label='Next Page']",
        "//a[@rel='next']",
        "//a[text()='»']", # Common symbol for next
        "//a[text()='>']", # Common symbol for next
        "//li[contains(@class, 'pagination-next')]/a", # Common class for next page in lists
        "//a[contains(@class, 'next')]", # Link with 'next' in its class
    ]

    for xpath in xpaths:
        try:
            # Wait for the element to be clickable
            next_link_element = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            href = next_link_element.get_attribute('href')
            if href:
                logging.info(f"Found next page link: {href} using xpath: {xpath}")
                return href
        except (NoSuchElementException, TimeoutException):
            continue
    logging.info("No next page link found.")
    return None

def _handle_pagination(driver, job_id, initial_url, initial_domain, max_depth, visited_urls, queued_urls, crawled_data, urls_to_visit_queue):
    """
    Handles pagination at depth 0 before proceeding to deeper levels.
    """
    urls_to_process_at_depth_0 = deque([(initial_url, 0)])

    while urls_to_process_at_depth_0:
        current_url, current_depth = urls_to_process_at_depth_0.popleft()

        if current_url in visited_urls:
            logging.info(f"Skipping already processed paginated URL: {current_url}")
            continue

        logging.info(f"Crawling paginated URL: {current_url} (Depth: {current_depth})")
        try:
            driver.get(current_url)
            body_text = driver.find_element(By.TAG_NAME, 'body').text
            text_bytes = body_text.encode('utf-8')
            text_size = len(text_bytes)
            warning = None

            if text_size > MAXIMUM_DOWNLOAD_SIZE:
                warning = f"Text content exceeded {MAXIMUM_DOWNLOAD_SIZE} bytes and was truncated."
                body_text = text_bytes[:MAXIMUM_DOWNLOAD_SIZE].decode('utf-8', errors='ignore')

            crawled_data.append({
                'url': current_url,
                'text': body_text,
                'size_bytes': text_size,
                'warning': warning
            })
            visited_urls.add(current_url)

            # Extract links for the next depth from this paginated page
            new_links = _get_links_from_page(driver, current_url, initial_domain, current_depth, max_depth, visited_urls, queued_urls)
            for link, depth in new_links:
                if link not in queued_urls:
                    urls_to_visit_queue.append((link, depth))
                    queued_urls.add(link)

            # Find and queue the next page at the same depth (0)
            next_page_url = _find_next_page_link(driver)
            if next_page_url:
                clean_next_page_url = _canonicalize_url(urljoin(current_url, next_page_url))
                parsed_next_url = urlparse(clean_next_page_url)
                # Ensure the next page is still within the initial domain and not already processed
                if _normalize_domain(parsed_next_url.netloc) == _normalize_domain(initial_domain) and \
                   clean_next_page_url not in visited_urls:
                    urls_to_process_at_depth_0.append((clean_next_page_url, 0))
                else:
                    logging.info(f"Next page link {clean_next_page_url} is outside initial domain or already processed. Stopping pagination.")
            else:
                logging.info("No more next page links found for pagination.")


        except Exception as e:
            logging.error(f"Error crawling paginated {current_url} for job {job_id}: {e}", exc_info=True)
            crawled_data.append({
                'url': current_url,
                'text': '',
                'size_bytes': 0,
                'error': str(e)
            })
            # If an error occurs, stop processing further paginated pages to avoid infinite loops on broken links
            break

def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Uses a headless browser to recursively navigate to a URL and extract all visible text.
    """
    initial_url = params.get('url')
    if not initial_url:
        raise ValueError("'url' parameter is missing for 'full_recursive_download'")

    if not urlparse(initial_url).scheme:
        initial_url = 'https://' + initial_url

    initial_url = _canonicalize_url(initial_url)
    max_depth = params.get('max_depth', DEFAULT_MAX_DEPTH)
    more_content_button_text = params.get('more_content_button_text')

    job_download_dir = os.path.join(download_dir, job_id)
    os.makedirs(job_download_dir, exist_ok=True)

    driver = None
    service = None
    crawled_data = []
    visited_urls = set()
    urls_to_visit = deque() # This queue will hold links for depth > 0, or all links if not pagination mode
    queued_urls = {initial_url} # Tracks all URLs that are either visited or in any queue
    initial_domain = urlparse(initial_url).netloc

    try:
        driver, service = _setup_driver(job_download_dir)

        if more_content_button_text == "Pagination":
            # Handle all paginated pages at depth 0 first
            _handle_pagination(driver, job_id, initial_url, initial_domain, max_depth, visited_urls, queued_urls, crawled_data, urls_to_visit)
        else:
            # If not pagination, start with the initial URL at depth 0
            urls_to_visit.append((initial_url, 0))

        # Now process the rest of the links (depth > 0 or all links if not pagination)
        while urls_to_visit:
            current_url, current_depth = urls_to_visit.popleft()
            queued_urls.discard(current_url)

            if current_url in visited_urls:
                logging.info(f"Skipping already crawled URL: {current_url}")
                continue

            logging.info(f"Crawling URL: {current_url} (Depth: {current_depth})")

            try:
                driver.get(current_url)
                # Only click "more content" button if not in pagination mode
                if more_content_button_text != "Pagination":
                    _click_more_button(driver, more_content_button_text)

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
                visited_urls.add(current_url)

                new_links = _get_links_from_page(driver, current_url, initial_domain, current_depth, max_depth, visited_urls, queued_urls)
                for link, depth in new_links:
                    if link not in queued_urls:
                        urls_to_visit.append((link, depth))
                        queued_urls.add(link)

            except Exception as e:
                logging.error(f"Error crawling {current_url} for job {job_id}: {e}", exc_info=True)
                crawled_data.append({
                    'url': current_url,
                    'text': '',
                    'size_bytes': 0,
                    'error': str(e)
                })

        result = {
            'job_id': job_id,
            'status':'complete',
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
        time.sleep(1)
        if driver and hasattr(driver, 'temp_dir'):
            try:
                shutil.rmtree(driver.temp_dir)
            except OSError as e:
                logging.warning(f"Could not remove temporary directory {driver.temp_dir}: {e}")

    write_result_to_outbound(job_id, result)

if __name__ == '__main__':
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

    test_download_dir = tempfile.gettempdir()

    def print_result_to_console(job_id, result):
        """A mock writer function that prints the result to the console."""
        print(json.dumps(result, indent=2))

    execute(test_job_id, test_params, test_download_dir, print_result_to_console)
