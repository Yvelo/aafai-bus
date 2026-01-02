import logging
import os
import shutil
import sys
from unittest.mock import MagicMock

# BEGIN: Monkey patch for distutils
if sys.version_info >= (3, 12):
    try:
        import packaging.version
        
        # Create a factory function that returns a Version object with `version` and `vstring` attributes
        def loose_version_factory(vstring):
            v = packaging.version.Version(vstring)
            v.version = v.release
            v.vstring = vstring
            return v

        sys.modules['distutils.version'] = MagicMock()
        sys.modules['distutils.version'].LooseVersion = loose_version_factory

    except ImportError:
        logging.warning("Could not apply distutils monkey patch: 'packaging' module not found.")
# END: Monkey patch for distutils

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import tempfile
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import json
import re
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains

# Base URL for Espacenet
ESPACENET_BASE_URL = "https://worldwide.espacenet.com/"

# Default maximum number of patents to scrape if not overridden by inbound message
DEFAULT_MAX_NUMBER_OF_PATENTS = 1000


def _setup_driver(job_download_dir, download_dir):
    """Configures and returns a headless Chrome WebDriver instance using undetected-chromedriver."""
    options = uc.ChromeOptions()

    headless = os.environ.get('HEADLESS_BROWSER', 'true').lower() == 'true'
    if headless:
        options.add_argument('--headless=new')

    # Common browser options
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-crash-reporter")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-in-process-stack-traces")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    options.add_argument("--window-.size=4000,2000")

    temp_dir = tempfile.mkdtemp()
    user_data_dir = os.path.join(temp_dir, "user-data")

    # undetected-chromedriver will handle driver download and patching.
    driver = uc.Chrome(
        options=options,
        user_data_dir=user_data_dir
    )

    driver.set_page_load_timeout(30)
    driver.temp_dir = temp_dir  # Store temp_dir for later cleanup
    return driver


def _get_field(element, selector):
    """Safely extracts text from an element using a CSS selector."""
    try:
        return element.find_element(By.CSS_SELECTOR, selector).text
    except (NoSuchElementException, StaleElementReferenceException):
        return None

def _parse_single_patent(patent_element):
    """
    Parses a single Espacenet patent element from the new UI.
    """
    patent_data = {}
    
    try:
        title_element = patent_element.find_element(By.CSS_SELECTOR, 'span.item__content--title--dYTuyzV6')
        patent_data['title'] = title_element.text
    except (NoSuchElementException, StaleElementReferenceException):
        patent_data['title'] = None

    try:
        # Extract patent number from the subtitle
        subtitle_element = patent_element.find_element(By.CSS_SELECTOR, 'div.h3--pyjtCj5Y.item__content--subtitle--mFxM6gqw')
        patent_data['patent_number'] = subtitle_element.find_element(By.TAG_NAME, 'span').text
    except (NoSuchElementException, StaleElementReferenceException):
        return None # Cannot proceed without a patent number

    if patent_data.get('patent_number'):
        patent_data['link'] = f"https://worldwide.espacenet.com/patent/search?q=pn%3D{patent_data['patent_number']}"

    patent_data['date_published'] = _get_field(patent_element, 'div.h3--pyjtCj5Y.item__content--subtitle--mFxM6gqw span:nth-child(2)')
    patent_data['applicant'] = _get_field(patent_element, 'div.h3--pyjtCj5Y.item__content--subtitle--mFxM6gqw div[aria-label="Applicant"] span')
    patent_data['abstract'] = _get_field(patent_element, 'div.item__content-abstract--hRLdiD1n')

    return patent_data


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Performs a Espacenet patent search based on the provided queries,
    scrapes the results, and returns them in the outbound JSON message.
    """
    logging.info(f"Executing search_espacenet for job {job_id} with params: {json.dumps(params, indent=2)}")
    queries = params.get('queries', [])
    if not queries:
        raise ValueError("'queries' parameter is missing or empty for 'search_espacenet'")

    max_patents = params.get('max_number_of_patents', DEFAULT_MAX_NUMBER_OF_PATENTS)
    job_download_dir = os.path.join(download_dir, job_id)
    os.makedirs(job_download_dir, exist_ok=True)
    driver = None
    all_patents = {}

    try:
        # --- Stage 1: Main search to collect patent metadata ---
        driver = _setup_driver(job_download_dir, download_dir)

        logging.info(f"Navigating to Espacenet URL: {ESPACENET_BASE_URL}")
        try:
            driver.get(ESPACENET_BASE_URL)
        except TimeoutException:
            logging.warning("Initial page load timed out, but continuing.")

        for query_keywords in queries:
            query = " AND ".join(query_keywords)
            logging.info(f"Performing search for query: '{query}'")

            try:
                search_input = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "input.search__input--qMUfUT1V")))
                search_input.clear()
                search_input.send_keys(query)
                time.sleep(1)
                search_button = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.search__button--xs1xtYK9")))
                search_button.click()
                logging.info("Search submitted.")
                WebDriverWait(driver, 40).until(EC.presence_of_element_located((By.CSS_SELECTOR, "article.item--wSceB4di")))
                logging.info("Search results loaded.")
            except (TimeoutException, NoSuchElementException) as e:
                logging.warning(f"Failed to perform search or find results for '{query}': {e}", exc_info=True)
                continue

            try:
                scrollable_element = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.publications-list--9wu4rcWN")))
                logging.info("Scrollable results container found.")
            except TimeoutException:
                logging.error("Could not find the scrollable results container.")
                continue

            last_patent_count = -1
            while last_patent_count != len(all_patents) and len(all_patents) < max_patents:
                last_patent_count = len(all_patents)
                patent_elements = driver.find_elements(By.CSS_SELECTOR, "article.item--wSceB4di")
                for element in patent_elements:
                    if len(all_patents) >= max_patents: break
                    parsed_patent = _parse_single_patent(element)
                    if parsed_patent and parsed_patent.get("patent_number"):
                        patent_number = parsed_patent["patent_number"]
                        if patent_number not in all_patents:
                            parsed_patent['keyword_matches'] = len(query_keywords)
                            all_patents[patent_number] = parsed_patent
                        elif len(query_keywords) > all_patents[patent_number].get('keyword_matches', 0):
                            all_patents[patent_number]['keyword_matches'] = len(query_keywords)
                if len(all_patents) >= max_patents:
                    logging.info(f"Reached max patents limit of {max_patents}.")
                    break
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", scrollable_element)
                time.sleep(2)
            logging.info(f"Scraping finished for query '{query}'.")
        
        final_patents = list(all_patents.values())
        final_patents.sort(key=lambda x: x.get('keyword_matches', 0), reverse=True)
        result = {'job_id': job_id, 'status': 'complete', 'result': {'total_patents_scraped': len(final_patents), 'patents': final_patents}}

    except Exception as e:
        logging.error(f"An error occurred during Espacenet search for job {job_id}: {e}", exc_info=True)
        result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
    finally:
        if driver:
            driver.quit()
            time.sleep(1)
            if hasattr(driver, 'temp_dir'):
                try:
                    shutil.rmtree(driver.temp_dir)
                except OSError as e:
                    logging.warning(f"Could not remove temporary directory {driver.temp_dir}: {e}")
        if os.path.exists(job_download_dir):
            try:
                shutil.rmtree(job_download_dir)
            except OSError as e:
                logging.warning(f"Could not remove job download directory {job_download_dir}: {e}")

    logging.info(f"Sending result for job {job_id}: {json.dumps(result, indent=2)}")
    write_result_to_outbound(job_id, result)


if __name__ == '__main__':
    import sys
    import uuid
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    if len(sys.argv) < 2:
        print("Usage: python search_espacenet.py <JSON_PARAMS_STRING>")
        sys.exit(1)
    try:
        test_params = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON params: {e}")
        sys.exit(1)
    test_job_id = f"test-espacenet-job-{uuid.uuid4()}"
    test_download_dir = tempfile.gettempdir()
    def print_result_to_console(job_id, result):
        print(json.dumps(result, indent=2))
    execute(test_job_id, test_params, test_download_dir, print_result_to_console)
