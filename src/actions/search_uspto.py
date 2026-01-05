import logging
import os
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager
import tempfile
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import json
import re
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains

# Base URL for USPTO
USPTO_BASE_URL = "https://ppubs.uspto.gov/pubwebapp/"

# Default maximum number of patents to scrape if not overridden by inbound message
DEFAULT_MAX_NUMBER_OF_PATENTS = 1000
MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION = 25


def _setup_driver(job_download_dir):
    """Configures and returns a headless Chrome WebDriver instance."""
    chrome_options = Options()
    if os.environ.get('HEADLESS_BROWSER', 'true').lower() == 'true':
        chrome_options.add_argument("--headless=new")
    
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
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36")
    chrome_options.add_argument("--window-size=1920,1080")

    # Anti-scraping measures from original implementation
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

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

    # Use a persistent cache for WebDriver Manager
    persistent_cache_dir = os.path.join(os.path.expanduser("~"), ".aafai-bus-cache", "drivers")
    os.makedirs(persistent_cache_dir, exist_ok=True)
    
    # Enable verbose logging for chromedriver
    chromedriver_log_path = os.path.join(job_download_dir, "chromedriver.log")
    service = Service(ChromeDriverManager(cache_manager=DriverCacheManager(root_dir=persistent_cache_dir)).install(), service_args=['--verbose', f'--log-path={chromedriver_log_path}'])

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

def _parse_single_patent(patent_element):
    """
    Parses a single USPTO patent element from the new UI.
    The script uses a wide browser window, so all columns in the results grid should be visible,
    eliminating the need for horizontal scrolling (the "horizontal elevator").
    """
    patent_data = {}
    
    try:
        # Extract patent number from the checkbox 'data-docid' attribute
        checkbox = patent_element.find_element(By.CSS_SELECTOR, 'input.row-select-check')
        patent_number = checkbox.get_attribute('data-docid')
        patent_data['patent_number'] = patent_number
    except (NoSuchElementException, StaleElementReferenceException):
        return None # Cannot proceed without a patent number

    if patent_number:
        patent_data['link'] = f"{USPTO_BASE_URL}#docid={patent_number}&page=1"

    # Extract various fields using the helper
    patent_data['result_number'] = _get_field(patent_element, 'div.result-num')
    patent_data['date_published'] = _get_field(patent_element, 'div[aria-describedby$="datePublished"]')
    patent_data['pages'] = _get_field(patent_element, 'div[aria-describedby$="pageCount"]')
    patent_data['inventor'] = _get_field(patent_element, 'div[aria-describedby$="inventorsShort"]')
    patent_data['assignee'] = _get_field(patent_element, 'div[aria-describedby$="assigneeName"]')
    patent_data['filing_date'] = _get_field(patent_element, 'div[aria-describedby$="applicationFilingDate"]')
    patent_data['application_number'] = _get_field(patent_element, 'div[aria-describedby$="applicationNumber"]')
    patent_data['applicant_name'] = _get_field(patent_element, 'div[aria-describedby$="applicantName"]')
    
    try:
        title_element = patent_element.find_element(By.CSS_SELECTOR, 'div[aria-describedby$="inventionTitle"] span')
        patent_data['title'] = title_element.get_attribute('title') or title_element.text
    except (NoSuchElementException, StaleElementReferenceException):
        patent_data['title'] = None

    return patent_data


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Performs a USPTO patent search based on the provided queries,
    scrapes the results, and returns them in the outbound JSON message.
    """
    logging.info(f"Executing search_uspto for job {job_id} with params: {json.dumps(params, indent=2)}")
    queries = params.get('queries', [])
    if not queries:
        raise ValueError("'queries' parameter is missing or empty for 'search_uspto'")

    max_patents = params.get('max_number_of_patents', DEFAULT_MAX_NUMBER_OF_PATENTS)
    job_download_dir = os.path.join(download_dir, job_id)
    os.makedirs(job_download_dir, exist_ok=True)
    driver = None
    all_patents = {}
    queries_in_session = 0

    try:
        # --- Stage 1: Main search to collect patent metadata ---
        driver = _setup_driver(job_download_dir)
        queries_in_session = 0
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        logging.info(f"Navigating to USPTO URL: {USPTO_BASE_URL}")
        try:
            driver.get(USPTO_BASE_URL)
        except TimeoutException:
            logging.warning("Initial page load timed out, but continuing.")

        try:
            WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.ID, "cookie-disclaimer-button"))).click()
            logging.info("Dismissed cookie disclaimer.")
        except TimeoutException:
            logging.info("No cookie disclaimer found or could not be closed.")
        
        try:
            close_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@aria-label, 'close') or contains(@aria-label, 'Close')]"))
            )
            close_button.click()
            logging.info("Closed a pop-up banner.")
        except TimeoutException:
            logging.info("No generic pop-up banner found.")

        for query_keywords in queries:
            if queries_in_session >= MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION:
                logging.info(f"Reached query limit for session ({MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION}). Restarting driver.")
                driver.quit()
                time.sleep(2)
                driver = _setup_driver(job_download_dir)
                queries_in_session = 0
                driver.get(USPTO_BASE_URL)
                try:
                    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.ID, "cookie-disclaimer-button"))).click()
                except TimeoutException:
                    pass
            
            queries_in_session += 1
            processed_keywords = []
            for keyword in query_keywords:
                stripped_keyword = keyword.strip()
                if ' ' in stripped_keyword and not (stripped_keyword.startswith('"') and stripped_keyword.endswith('"')):
                    processed_keywords.append(f'"{stripped_keyword}"')
                else:
                    processed_keywords.append(stripped_keyword)
            query = " AND ".join(processed_keywords)
            logging.info(f"Performing search for query: '{query}'")

            total_patents_found = 0
            try:
                search_input = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "trix-editor")))
                actions = ActionChains(driver)
                actions.click(search_input).perform()
                time.sleep(0.5)
                driver.execute_script("arguments[0].editor.loadHTML('')", search_input)
                search_input.send_keys(query)
                time.sleep(1)
                search_button = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "search-btn-search")))
                search_button.click()
                logging.info("Search submitted.")
                
                # Wait for the result bar to appear, which indicates the search is complete
                WebDriverWait(driver, 40).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".resultBar.resultInfo")))
                logging.info("Search results page loaded.")

                # Extract total number of patents and check for no results
                try:
                    total_patents_element = driver.find_element(By.CSS_SELECTOR, ".resultNumber")
                    total_patents_text = total_patents_element.text.replace(',', '')
                    if total_patents_text:
                        total_patents_found = int(total_patents_text)
                    else:
                        total_patents_found = 0
                    logging.info(f"Total patents found for query '{query}': {total_patents_found}")
                    if total_patents_found == 0:
                        logging.warning(f"No patents found for query: '{query}'")
                        continue # Move to the next query
                except (NoSuchElementException, ValueError) as e:
                    logging.warning(f"Could not extract the total number of patents found for query '{query}', assuming 0 results. Error: {e}")
                    continue

            except (TimeoutException, NoSuchElementException) as e:
                logging.warning(f"Failed to perform search or find results for '{query}': {e}", exc_info=True)
                continue

            try:
                # Wait for at least one row to be present before starting to scrape
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#search-results-table .grid-canvas .slick-row")))
                scrollable_element = driver.find_element(By.CSS_SELECTOR, "div.slick-viewport")
                logging.info("Scrollable results container and rows found.")
            except TimeoutException:
                logging.error("Could not find the scrollable results container or initial patent rows.")
                continue

            # Scrape visible patents and scroll until no new patents are found or max is reached
            last_height = -1
            current_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_element)
            
            while len(all_patents) < max_patents:
                patent_elements = driver.find_elements(By.CSS_SELECTOR, "#search-results-table .grid-canvas .slick-row")
                for element in patent_elements:
                    if len(all_patents) >= max_patents:
                        break
                    parsed_patent = _parse_single_patent(element)
                    if parsed_patent and parsed_patent.get("patent_number"):
                        patent_number = parsed_patent["patent_number"]
                        
                        if patent_number not in all_patents:
                            logging.info(f"New patent found: {patent_number} with query '{query}'")
                            parsed_patent['keyword_matches'] = len(query_keywords)
                            parsed_patent['matching_keywords'] = query_keywords
                            parsed_patent['total_patents_in_query'] = total_patents_found
                            all_patents[patent_number] = parsed_patent
                        elif len(query_keywords) > all_patents[patent_number].get('keyword_matches', 0):
                            logging.info(f"Updating patent {patent_number} with a better keyword match from query '{query}'")
                            all_patents[patent_number]['keyword_matches'] = len(query_keywords)
                            all_patents[patent_number]['matching_keywords'] = query_keywords
                            all_patents[patent_number]['total_patents_in_query'] = total_patents_found

                # Scroll down
                driver.execute_script("arguments[0].scrollTop += arguments[0].clientHeight;", scrollable_element)
                time.sleep(2) # Wait for new content to load
                
                new_height = driver.execute_script("return arguments[0].scrollHeight", scrollable_element)
                if new_height == last_height:
                    # If scroll height hasn't changed, we've likely reached the end
                    break
                last_height = new_height

            logging.info(f"Scraping finished for query '{query}'.")
        
        # --- Stage 2: Fetch abstracts for all collected patents using the same session ---
        logging.info(f"Initial scraping complete. Found {len(all_patents)} unique patents. Now fetching abstracts...")
        patents_to_update = list(all_patents.values())

        for i, patent in enumerate(patents_to_update):
            if queries_in_session >= MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION:
                logging.info(f"Reached query limit for session ({MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION}). Restarting driver for abstract fetching.")
                driver.quit()
                time.sleep(2)
                driver = _setup_driver(job_download_dir)
                queries_in_session = 0
                # After restarting, navigate to the base URL to ensure a clean state
                driver.get(USPTO_BASE_URL)
                time.sleep(2) # Allow time for the page to load and stabilize

            patent_number = patent.get("patent_number")
            if not patent_number:
                continue
            
            # Skip if abstract has already been successfully fetched
            if 'abstract' in all_patents[patent_number] and all_patents[patent_number]['abstract'] not in ["Abstract not fetched.", "Error fetching abstract.", "Abstract section was empty."]:
                logging.info(f"Skipping abstract fetch for {patent_number}, already have it.")
                continue

            logging.info(f"Fetching abstract for patent {i + 1}/{len(patents_to_update)}: {patent_number}")
            all_patents[patent_number]['abstract'] = "Abstract not fetched."
            queries_in_session += 1
            
            try:
                # Use the search bar to find the patent by its number
                search_input = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "trix-editor")))
                actions = ActionChains(driver)
                actions.click(search_input).perform()
                time.sleep(0.5)
                driver.execute_script("arguments[0].editor.loadHTML('')", search_input)
                search_input.send_keys(patent_number)
                time.sleep(1)
                search_button = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "search-btn-search")))
                search_button.click()

                # Handle pop-ups after search
                try:
                    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "cookie-disclaimer-button"))).click()
                    logging.info(f"Dismissed cookie disclaimer for {patent_number}.")
                except TimeoutException:
                    pass
                
                try:
                    close_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(@aria-label, 'close') or contains(@aria-label, 'Close')]"))
                    )
                    close_button.click()
                    logging.info("Closed a pop-up banner.")
                except TimeoutException:
                    pass

                abstract_container = WebDriverWait(driver, 20).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.abstractNode div.abstract")))
                paragraphs = abstract_container.find_elements(By.TAG_NAME, 'p')
                abstract_text = "\n".join([p.text for p in paragraphs if p.text])
                
                if abstract_text:
                    all_patents[patent_number]['abstract'] = abstract_text
                    logging.info(f"Successfully extracted abstract for {patent_number}")
                else:
                    all_patents[patent_number]['abstract'] = "Abstract section was empty."
                    logging.warning(f"Abstract section was empty for {patent_number}")

                # Update other fields from the detail page, as they are more reliable here.
                details_container = driver.find_element(By.CSS_SELECTOR, "div.docMetadata")

                # Inventor(s)
                try:
                    inventor_elements = details_container.find_elements(By.CSS_SELECTOR, "div.meta-inventorsInfoGroup .meta-col:nth-child(1) > div")
                    inventors = [elem.text.strip() for elem in inventor_elements if elem.text.strip()]
                    if inventors:
                        all_patents[patent_number]['inventor'] = "; ".join(inventors)
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

                # Assignee & Applicant Name
                try:
                    # Applicant name is consistently available
                    applicant_element = details_container.find_element(By.CSS_SELECTOR, "div.meta-applicantInfoGroup .clearfix .item:nth-child(1) .meta-col")
                    if applicant_element and applicant_element.text.strip():
                        applicant_name = applicant_element.text.strip()
                        all_patents[patent_number]['applicant_name'] = applicant_name
                        
                        # Check if this applicant is also the assignee
                        try:
                            type_element = details_container.find_element(By.CSS_SELECTOR, "div.meta-applicantInfoGroup .item-margin-top .meta-col")
                            if 'assignee' in type_element.text.lower():
                                all_patents[patent_number]['assignee'] = applicant_name
                        except (NoSuchElementException, StaleElementReferenceException):
                            pass # No type info, can't confirm assignee
                except (NoSuchElementException, StaleElementReferenceException):
                    pass
                
                # Try to find a dedicated assignee field, which would be more accurate
                try:
                    assignee_element = details_container.find_element(By.CSS_SELECTOR, "div.meta-assigneeInfoGroup .clearfix .item:nth-child(1) .meta-col div")
                    if assignee_element and assignee_element.text.strip():
                        all_patents[patent_number]['assignee'] = assignee_element.text.strip()
                except (NoSuchElementException, StaleElementReferenceException):
                    pass # No dedicated assignee group, rely on applicant info if available

                # Filing Date
                try:
                    filing_date_element = details_container.find_element(By.XPATH, ".//h3[contains(., 'Date Filed')]/following-sibling::div")
                    if filing_date_element and filing_date_element.text.strip():
                        all_patents[patent_number]['filing_date'] = filing_date_element.text.strip()
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

                # Application Number
                try:
                    app_num_element = details_container.find_element(By.XPATH, ".//h3[contains(., 'Application NO')]/following-sibling::div")
                    if app_num_element and app_num_element.text.strip():
                        all_patents[patent_number]['application_number'] = app_num_element.text.strip()
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

            except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as e:
                logging.warning(f"Could not fetch abstract for {patent_number}: {e}", exc_info=True)
                all_patents[patent_number]['abstract'] = "Error fetching abstract."
                # Navigate back to base URL to reset state for the next attempt
                try:
                    driver.get(USPTO_BASE_URL)
                    time.sleep(2)
                except TimeoutException:
                    logging.error("Failed to navigate back to base URL after an error.")


        final_patents = list(all_patents.values())
        final_patents.sort(key=lambda x: x.get('keyword_matches', 0), reverse=True)
        result = {'job_id': job_id, 'status': 'complete', 'result': {'total_patents_scraped': len(final_patents), 'patents': final_patents}}

    except Exception as e:
        logging.error(f"An error occurred during USPTO search for job {job_id}: {e}", exc_info=True)
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
        print("Usage: python search_uspto.py <JSON_PARAMS_STRING>")
        sys.exit(1)
    try:
        test_params = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON params: {e}")
        sys.exit(1)
    test_job_id = f"test-uspto-job-{uuid.uuid4()}"
    test_download_dir = tempfile.gettempdir()
    def print_result_to_console(job_id, result):
        print(json.dumps(result, indent=2))
    execute(test_job_id, test_params, test_download_dir, print_result_to_console)
