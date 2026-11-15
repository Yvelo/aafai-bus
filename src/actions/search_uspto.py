import logging
import os
import shutil
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
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException, ElementClickInterceptedException
from selenium.webdriver.common.action_chains import ActionChains

# Base URL for USPTO
USPTO_BASE_URL = "https://ppubs.uspto.gov/pubwebapp/"

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
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36")
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


def _handle_initial_popups(driver):
    """Handles cookie disclaimers, modal dialogs, and other initial pop-ups."""
    # 1. Cookie disclaimer
    try:
        cookie_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "cookie-disclaimer-button")))
        cookie_btn.click()
        logging.info("Dismissed cookie disclaimer.")
    except TimeoutException:
        logging.info("No cookie disclaimer found or could not be closed.")

    # 2. Bootstrap/generic modal dialogs (e.g. .modal-dialog, .modal)
    modal_close_selectors = [
        "//div[contains(@class, 'modal')]//button[contains(@class, 'close')]",
        "//div[contains(@class, 'modal-dialog')]//button[contains(@class, 'btn-primary') or contains(@class, 'btn-secondary') or contains(@class, 'close')]",
        "//div[contains(@class, 'modal')]//button[contains(translate(text(), 'OKCLOSE', 'okclose'), 'ok') or contains(translate(text(), 'OKCLOSE', 'okclose'), 'close') or contains(translate(text(), 'OKCLOSE', 'okclose'), 'dismiss') or contains(translate(text(), 'OKCLOSE', 'okclose'), 'accept') or contains(translate(text(), 'OKCLOSE', 'okclose'), 'continue')]",
        "//button[contains(@aria-label, 'close') or contains(@aria-label, 'Close')]",
    ]

    for selector in modal_close_selectors:
        try:
            buttons = driver.find_elements(By.XPATH, selector)
            for btn in buttons:
                if btn.is_displayed():
                    try:
                        btn.click()
                        logging.info(f"Closed modal/pop-up via selector: {selector}")
                        time.sleep(0.5)
                    except Exception:
                        driver.execute_script("arguments[0].click();", btn)
                        logging.info(f"Closed modal/pop-up via JS click: {selector}")
                        time.sleep(0.5)
        except Exception as e:
            logging.debug(f"Error checking modal selector {selector}: {e}")

    # 3. Wait for any open modal-backdrop or modal to disappear
    try:
        WebDriverWait(driver, 3).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, ".modal-backdrop, .modal.show, .modal-dialog"))
        )
    except TimeoutException:
        # If modal is still present, attempt hiding it via JS
        try:
            driver.execute_script("""
                document.querySelectorAll('.modal, .modal-backdrop, .modal-dialog').forEach(el => {
                    el.style.display = 'none';
                    el.classList.remove('show');
                });
                document.body.classList.remove('modal-open');
            """)
            logging.info("Forced removal of modal / backdrop via JavaScript.")
        except Exception:
            pass


def _click_search_button(driver, timeout=20):
    """
    Submits search directly via JavaScript click or form submission to avoid
    ElementClickInterceptedException caused by lingering or asynchronous modal dialogs.
    Falls back to normal click and popup dismissal if necessary.
    """
    search_button = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.ID, "search-btn-search")))
    try:
        # Direct JS click bypasses viewport coordinate hit-testing and overlays like modal-dialog
        driver.execute_script("arguments[0].click();", search_button)
    except Exception as js_err:
        logging.warning(f"JS click on search_button failed ({js_err}); attempting popup cleanup and standard click.")
        _handle_initial_popups(driver)
        search_button = driver.find_element(By.ID, "search-btn-search")
        try:
            search_button.click()
        except ElementClickInterceptedException:
            # Dismiss popups again and force JS click
            _handle_initial_popups(driver)
            driver.execute_script("arguments[0].click();", search_button)


def _format_single_keyword(term):
    """
    Formats a single keyword or phrase. Encloses phrases containing spaces in double quotes.
    """
    stripped = term.strip()
    if ' ' in stripped and not (stripped.startswith('"') and stripped.endswith('"')):
        return f'"{stripped}"'
    return stripped


def _build_uspto_query(query_keywords):
    """
    Builds a boolean query string from a list of keyword items.
    Items with semicolons (e.g. 'cGAS; cGAMP; STING') represent OR-groups:
    ("cGAS" OR "cGAMP" OR "STING").
    Different items in query_keywords are combined with AND:
    ("cGAS" OR "cGAMP" OR "STING") AND ("LNP" OR "Lipid Nanoparticle")
    """
    processed_keywords = []
    for keyword in query_keywords:
        if ';' in keyword:
            alternatives = [alt.strip() for alt in keyword.split(';') if alt.strip()]
            if len(alternatives) > 1:
                or_group = " OR ".join(_format_single_keyword(alt) for alt in alternatives)
                processed_keywords.append(f"({or_group})")
            elif alternatives:
                processed_keywords.append(_format_single_keyword(alternatives[0]))
        else:
            processed_keywords.append(_format_single_keyword(keyword))
    return " AND ".join(processed_keywords)


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

        _handle_initial_popups(driver)

        for query_keywords in queries:
            if queries_in_session >= MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION:
                logging.info(f"Reached query limit for session ({MAXIMUM_NUMBER_OF_QUERIES_PER_SESSION}). Restarting driver.")
                driver.quit()
                time.sleep(2)
                driver = _setup_driver(job_download_dir)
                queries_in_session = 0
                driver.get(USPTO_BASE_URL)
                _handle_initial_popups(driver)
            
            queries_in_session += 1
            query = _build_uspto_query(query_keywords)
            logging.info(f"Performing search for query: '{query}'")

            total_patents_found = 0
            try:
                _handle_initial_popups(driver)
                search_input = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "trix-editor")))
                actions = ActionChains(driver)
                actions.click(search_input).perform()
                time.sleep(0.5)
                driver.execute_script("arguments[0].editor.loadHTML('')", search_input)
                search_input.send_keys(query)
                time.sleep(1)
                _click_search_button(driver)
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
            patents_scraped_for_this_query = set()
            last_height = -1
            
            while len(patents_scraped_for_this_query) < max_patents:
                patent_elements = driver.find_elements(By.CSS_SELECTOR, "#search-results-table .grid-canvas .slick-row")
                for element in patent_elements:
                    if len(patents_scraped_for_this_query) >= max_patents:
                        break
                    parsed_patent = _parse_single_patent(element)
                    if parsed_patent and parsed_patent.get("patent_number"):
                        patent_number = parsed_patent["patent_number"]
                        
                        patents_scraped_for_this_query.add(patent_number)

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
                driver.get(USPTO_BASE_URL)
                _handle_initial_popups(driver)

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
                _click_search_button(driver)

                # Handle pop-ups that might appear after a search
                _handle_initial_popups(driver)

                abstract_container = WebDriverWait(driver, 20).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.abstractNode div.abstract")))
                abstract_text = abstract_container.text.strip()
                if abstract_text:
                    all_patents[patent_number]['abstract'] = abstract_text
                else:
                    all_patents[patent_number]['abstract'] = "Abstract section was empty."

            except (TimeoutException, NoSuchElementException) as e:
                logging.warning(f"Could not fetch abstract for {patent_number}: {e}")
                all_patents[patent_number]['abstract'] = "Error fetching abstract."

                # --- Enhanced Debugging: Save screenshot and page source ---
                try:
                    # Save screenshot
                    screenshot_path = os.path.join(job_download_dir, f"error_{patent_number}.png")
                    driver.save_screenshot(screenshot_path)
                    logging.info(f"Saved screenshot to {screenshot_path}")

                    # Save page source
                    page_source_path = os.path.join(job_download_dir, f"error_{patent_number}.html")
                    with open(page_source_path, "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logging.info(f"Saved page source to {page_source_path}")
                except Exception as debug_e:
                    logging.error(f"Could not save debug info: {debug_e}")
                # --- End Enhanced Debugging ---


                all_patents[patent_number]['abstract'] = "Error fetching details."

                # Force-restart the driver to get a clean session
                logging.info("Encountered an error. Restarting browser session to recover.")
                driver.quit()
                time.sleep(2)
                driver = _setup_driver(job_download_dir)
                queries_in_session = 0
                driver.get(USPTO_BASE_URL) # Start fresh
                _handle_initial_popups(driver)


        final_patents = list(all_patents.values())
        final_patents.sort(key=lambda x: x.get('keyword_matches', 0), reverse=True)
        result = {'job_id': job_id, 'status': 'Completed', 'result': {'total_patents_scraped': len(final_patents), 'patents': final_patents}}

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
