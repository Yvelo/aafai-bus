import logging
import os
import shutil
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from src.browser_config import get_chrome_options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager
import tempfile
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import json
import re
from selenium.common.exceptions import (TimeoutException, NoSuchElementException,
                                        StaleElementReferenceException, ElementClickInterceptedException,
                                        WebDriverException)
from selenium.webdriver.common.action_chains import ActionChains

# Base URL for WIPO
WIPO_BASE_URL = "https://patentscope.wipo.int/search/en/search.jsf"

# Default maximum number of patents to scrape if not overridden by inbound message
DEFAULT_MAX_NUMBER_OF_PATENTS = 1000
MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION = 25


def _setup_driver(job_download_dir):
    """Configures and returns a headless Chrome WebDriver instance."""
    chrome_options = get_chrome_options()
    
    # Common browser options for stability
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-crash-reporter")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-in-process-stack-traces")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--disable-dev-tools")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/108.0.0.0 Safari/537.36")
    chrome_options.add_argument("--window-size=1920,1080")

    # Anti-scraping measures from original implementation
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # Use a persistent cache in the system's temp directory for WebDriver Manager
    persistent_cache_dir = os.path.join(tempfile.gettempdir(), ".aafai-bus-cache", "drivers")
    os.makedirs(persistent_cache_dir, exist_ok=True)

    # Create a single, persistent temporary directory for this driver instance.
    temp_dir = tempfile.mkdtemp()

    # **CRITICAL FIX**: Set the HOME environment variable for the Chrome process.
    os.environ['HOME'] = temp_dir

    # Define paths within our new temporary HOME directory
    user_data_dir = os.path.join(temp_dir, "user-data")
    disk_cache_dir = os.path.join(temp_dir, "cache")
    crash_dumps_dir = os.path.join(temp_dir, "crash-dumps")

    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_options.add_argument(f"--disk-cache-dir={disk_cache_dir}")
    chrome_options.add_argument(f"--crash-dumps-dir={crash_dumps_dir}")
    
    # Enable verbose logging for chromedriver
    chromedriver_log_path = os.path.join(job_download_dir, "chromedriver.log")
    service = Service(ChromeDriverManager(cache_manager=DriverCacheManager(root_dir=persistent_cache_dir)).install(),
                      service_args=['--verbose', f'--log-path={chromedriver_log_path}'])

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)

    # Store the temporary directory path so it can be cleaned up later
    driver.temp_dir = temp_dir

    return driver


def _get_field(element, selector):
    """Safely extracts text from an element using a CSS selector."""
    try:
        return element.find_element(By.CSS_SELECTOR, selector).text
    except (NoSuchElementException, StaleElementReferenceException):
        return None


def _get_detail_field(driver, label):
    """Safely extracts a field from the patent detail page by its label."""
    try:
        xpath = (f"//span[contains(@class, 'ps-biblio-field--label') and .//span[contains(., '{label}')]]"
                 f"/following-sibling::span[contains(@class, 'ps-biblio-field--value')]")
        element = driver.find_element(By.XPATH, xpath)
        return element.text.strip()
    except (NoSuchElementException, StaleElementReferenceException):
        logging.debug(f"Could not find detail field for label: {label}")
        return None


def _solve_captcha_if_present(driver, job_download_dir, max_attempts=20):
    """
    Checks for psCaptchaForm and attempts to solve it by clicking an image.
    Returns True if solved or not present, False if failed.
    """
    captcha_attempts = 0
    while captcha_attempts < max_attempts:
        try:
            captcha_form = driver.find_element(By.ID, "psCaptchaForm")
            captcha_attempts += 1
            logging.warning(f"CAPTCHA detected. Attempt {captcha_attempts}/{max_attempts} to solve.")

            if "Wrong answer!" in driver.page_source:
                logging.warning("CAPTCHA answer rejected. Retrying next image.")

            images = captcha_form.find_elements(By.CSS_SELECTOR, "a[id^='click']")
            if not images:
                logging.error("CAPTCHA form found, but no images to click.")
                return False

            driver.execute_script("arguments[0].click();", random.choice(images))
            time.sleep(3)
        except NoSuchElementException:
            logging.info("CAPTCHA solved or not present.")
            return True

    logging.error(f"Failed to solve CAPTCHA after {max_attempts} attempts.")
    return False


def _parse_single_patent(patent_element):
    """
    Parses a single WIPO patent element from the results table row.
    """
    patent_data = {}

    try:
        # The 'data-rk' attribute on the table row is a reliable unique ID
        patent_number = patent_element.get_attribute('data-rk')
        if not patent_number:
            return None
        patent_data['patent_number'] = patent_number
        patent_data['link'] = f"https://patentscope.wipo.int/search/en/detail.jsf?docId={patent_number}"
    except (NoSuchElementException, StaleElementReferenceException):
        return None  # Cannot proceed without a patent number

    try:
        title_element = patent_element.find_element(By.CSS_SELECTOR, 'span.ps-patent-result--title--title')
        patent_data['title'] = title_element.text
    except (NoSuchElementException, StaleElementReferenceException):
        patent_data['title'] = None

    patent_data['inventor'] = _get_field(patent_element, 'span.ps-patent-result--inventor')
    patent_data['assignee'] = _get_field(patent_element, 'span.ps-patent-result--applicant')
    
    try:
        # The publication date is in a div with other text, so we get the specific span
        pub_date_container = patent_element.find_element(By.CSS_SELECTOR, 'div.ps-patent-result--title--ctr-pubdate')
        # Text is like "US - 24.08.2023", we want the date part
        patent_data['date_published'] = pub_date_container.text.split('-')[-1].strip()
    except (NoSuchElementException, StaleElementReferenceException):
        patent_data['date_published'] = None
    
    # Other fields might not be directly available on the result list, initialize them
    patent_data['result_number'] = None
    patent_data['pages'] = None
    patent_data['filing_date'] = None
    patent_data['application_number'] = None
    patent_data['applicant_name'] = patent_data['assignee']  # Often the same for WIPO results

    return patent_data


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Performs a WIPO patent search based on the provided queries,
    scrapes the results, and returns them in the outbound JSON message.
    """
    logging.info(f"Executing search_wipo for job {job_id} with params: {json.dumps(params, indent=2)}")
    queries = params.get('queries', [])
    brand = params.get('brand')

    if not queries and not brand:
        raise ValueError("Either 'queries' or 'brand' parameter must be provided for 'search_wipo'")

    max_patents_per_query = params.get('max_number_of_patents', DEFAULT_MAX_NUMBER_OF_PATENTS)
    job_download_dir = os.path.join(download_dir, job_id)
    os.makedirs(job_download_dir, exist_ok=True)
    driver = None
    all_patents = {}
    
    try:
        driver = _setup_driver(job_download_dir)
        driver.get(WIPO_BASE_URL)
        
        try:
            accept_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept All')]")))
            driver.execute_script("arguments[0].click();", accept_button)
            logging.info("Accepted all cookies.")
        except TimeoutException:
            logging.info("No cookie banner found or could not be closed.")

        # If only a brand is provided, we'll do one search. If queries are provided, we iterate through them.
        # If both are provided, we iterate through queries and add the brand to each.
        search_iterations = queries if queries else [[]]

        query_index = 0
        while query_index < len(search_iterations):
            query_keywords = search_iterations[query_index]
            
            if query_index > 0 and query_index % MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION == 0:
                logging.info(f"Reached query limit for session ({MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION}). "
                             f"Restarting driver.")
                driver.quit()
                time.sleep(2)
                driver = _setup_driver(job_download_dir)
                driver.get(WIPO_BASE_URL)
                try:
                    accept_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept All')]")))
                    driver.execute_script("arguments[0].click();", accept_button)
                    logging.info("Accepted all cookies.")
                except TimeoutException:
                    logging.info("No cookie banner found or could not be closed.")

            processed_keywords = [f'"{k.strip()}"' if ' ' in k.strip() else k.strip() for k in query_keywords]
            
            # Add brand to the query if it exists. The field code for "Applicant" (assignee) is 'PA'.
            if brand:
                processed_keywords.append(f'PA:("{brand}")')

            query = " AND ".join(processed_keywords)
            if not query:
                logging.warning("Empty query generated. Skipping.")
                query_index += 1
                continue
                
            logging.info(f"Performing search for query: '{query}'")

            try:
                # Solve CAPTCHA if initially present
                if not _solve_captcha_if_present(driver, job_download_dir):
                    logging.error("Failed to solve CAPTCHA. Restarting session and retrying query.")
                    driver.quit()
                    time.sleep(3)
                    driver = _setup_driver(job_download_dir)
                    driver.get(WIPO_BASE_URL)
                    continue

                # Determine which search form is available by checking for the presence of the search input fields.
                try:
                    # Try for the simple search form first (present on main page and sometimes on 'no results' pages)
                    search_input = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.ID, "simpleSearchForm:fpSearch:input")))
                    search_button_selector = "button.js-default-button"
                except TimeoutException:
                    # If simple form is not there, expect to be on a results page with an advanced search form.
                    try:
                        search_input = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.ID, "advancedSearchForm:advancedSearchInput:input")))
                        search_button_selector = "button.js-advanced-search-button"
                    except TimeoutException:
                        logging.error("Could not find a known search input field. Resetting page and retrying query.")
                        driver.get(WIPO_BASE_URL)
                        continue

                search_input.clear()
                search_input.send_keys(query)
                time.sleep(1)
                search_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, search_button_selector)))
                driver.execute_script("arguments[0].click();", search_button)
                logging.info("Search submitted.")

                def check_search_status(d):
                    if d.find_elements(By.ID, "results-container"):
                        return "results"
                    if d.find_elements(By.CSS_SELECTOR, "span.results-count, div.ps-no-result"):
                        return "count_or_no_result"
                    if d.find_elements(By.ID, "psCaptchaForm"):
                        return "captcha"
                    return False

                search_status = WebDriverWait(driver, 20).until(check_search_status)

                if search_status == "captcha":
                    logging.warning("CAPTCHA appeared after submitting search. Solving in-place...")
                    if _solve_captcha_if_present(driver, job_download_dir):
                        logging.info("In-place CAPTCHA solved. Continuing with query.")
                    else:
                        logging.warning("In-place CAPTCHA could not be solved. Retrying query.")
                    continue

                total_patents_found = 0
                total_patents_elements = driver.find_elements(By.CSS_SELECTOR, "span.results-count")
                if total_patents_elements:
                    count_text = total_patents_elements[0].text.replace(',', '').split()
                    if count_text:
                        try:
                            total_patents_found = int(count_text[0])
                        except ValueError:
                            total_patents_found = 0

                logging.info(f"Total patents found for query '{query}': {total_patents_found}")

                if total_patents_found == 0 or (
                        search_status == "count_or_no_result" and not driver.find_elements(By.ID, "results-container")):
                    query_index += 1
                    continue

                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "results-container")))
                logging.info("Search results container loaded.")

                patents_scraped_this_query = 0
                while patents_scraped_this_query < max_patents_per_query:
                    page_processed_successfully = False
                    for attempt in range(3):
                        try:
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "tr[data-rk]")))
                            patent_elements = driver.find_elements(By.CSS_SELECTOR, "tr[data-rk]")

                            for element in patent_elements:
                                if patents_scraped_this_query >= max_patents_per_query:
                                    break
                                parsed_patent = _parse_single_patent(element)
                                if parsed_patent and parsed_patent.get("patent_number"):
                                    patent_number = parsed_patent["patent_number"]

                                    if patent_number not in all_patents:
                                        patents_scraped_this_query += 1
                                        logging.info(f"New patent found: {patent_number} ({patents_scraped_this_query}/"
                                                     f"{max_patents_per_query}) with query '{query}'")
                                        parsed_patent['keyword_matches'] = len(query_keywords)
                                        parsed_patent['matching_keywords'] = query_keywords
                                        parsed_patent['total_patents_in_query'] = total_patents_found
                                        all_patents[patent_number] = parsed_patent
                                    elif len(query_keywords) > all_patents[patent_number].get('keyword_matches', 0):
                                        logging.info(
                                            f"Updating patent {patent_number} with a better keyword match from query "
                                            f"'{query}'")
                                        all_patents[patent_number]['keyword_matches'] = len(query_keywords)
                                        all_patents[patent_number]['matching_keywords'] = query_keywords
                                        all_patents[patent_number]['total_patents_in_query'] = total_patents_found
                            
                            page_processed_successfully = True
                            break

                        except StaleElementReferenceException:
                            logging.warning(
                                f"StaleElementReferenceException during page processing "
                                f"(attempt {attempt + 1}/3). Retrying.")
                            time.sleep(2)

                    if not page_processed_successfully:
                        logging.error(
                            "Failed to process page after 3 attempts due to StaleElementReferenceException.")
                        break
                    
                    if patents_scraped_this_query >= max_patents_per_query:
                        break

                    try:
                        WebDriverWait(driver, 10).until(
                            EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.ui-blockui-content")))
                        
                        for attempt in range(3):
                            try:
                                next_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
                                    (By.CSS_SELECTOR, "a.js-paginator-next:not(.ui-state-disabled)")))
                                driver.execute_script("arguments[0].click();", next_button)
                                break
                            except StaleElementReferenceException:
                                logging.warning(f"StaleElementReferenceException on 'next' button click, "
                                                f"attempt {attempt + 1}/3. Retrying...")
                                time.sleep(1)
                        else:
                            logging.error("Failed to click 'next' button due to repeated "
                                          "StaleElementReferenceExceptions.")
                            break

                    except (NoSuchElementException, TimeoutException, ElementClickInterceptedException):
                        logging.info("No more pages or 'next' button is not available.")
                        break
                
                query_index += 1

            except (TimeoutException, NoSuchElementException) as e:
                logging.warning(f"An error occurred during search for '{query}': {e}", exc_info=True)
                query_index += 1
                continue
        
        logging.info(f"Scraping complete. Found {len(all_patents)} unique patents. Now fetching details...")
        driver.set_page_load_timeout(15)
        for patent in all_patents.values():
            patent_number = patent.get('patent_number', 'unknown')
            try:
                driver.get(patent['link'])
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.ps-biblio-data--biblio-card")))
                
                try:
                    abstract_element = driver.find_element(By.CSS_SELECTOR, "div.patent-abstract")
                    patent['abstract'] = abstract_element.text
                except NoSuchElementException:
                    patent['abstract'] = "Abstract not found."

                patent['filing_date'] = (_get_detail_field(driver, 'Application Date')
                                         or _get_detail_field(driver, 'Filing Date'))
                patent['application_number'] = (_get_detail_field(driver, 'Application Number')
                                                or _get_detail_field(driver, 'Publication Number'))
                patent['date_published'] = _get_detail_field(driver, 'Publication Date') or patent['date_published']
                patent['inventor'] = _get_detail_field(driver, 'Inventors') or patent['inventor']
                patent['applicant_name'] = _get_detail_field(driver, 'Applicants') or patent['assignee']
                patent['assignee'] = patent['applicant_name']

            except TimeoutException:
                logging.info(f"Detail page not available or timed out for {patent_number}; keeping list metadata.")
            except WebDriverException as e:
                err_msg = e.msg.splitlines()[0] if hasattr(e, 'msg') and e.msg else str(e)
                logging.info(f"Could not load details for {patent_number}: {err_msg}")

        final_patents = list(all_patents.values())
        final_patents.sort(key=lambda x: x.get('keyword_matches', 0), reverse=True)
        result = {'job_id': job_id, 'status': 'Completed',
                  'result': {'total_patents_scraped': len(final_patents), 'patents': final_patents}}

    except Exception as e:
        logging.error(f"An error occurred during WIPO search for job {job_id}: {e}", exc_info=True)
        result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
    finally:
        if driver:
            driver.quit()
            if hasattr(driver, 'temp_dir'):
                shutil.rmtree(driver.temp_dir, ignore_errors=True)
        shutil.rmtree(job_download_dir, ignore_errors=True)

    logging.info(f"Sending result for job {job_id}: {json.dumps(result, indent=2)}")
    write_result_to_outbound(job_id, result)


if __name__ == '__main__':
    import sys
    import uuid
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    if len(sys.argv) < 2:
        print("Usage: python search_wipo.py <JSON_PARAMS_STRING>")
        sys.exit(1)
    test_params = json.loads(sys.argv[1])
    test_job_id = f"test-wipo-job-{uuid.uuid4()}"
    test_download_dir = tempfile.mkdtemp()

    def print_result_to_console(job_id, result):
        print(json.dumps(result, indent=2))
    execute(test_job_id, test_params, test_download_dir, print_result_to_console)
