import logging
import os
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import tempfile
from urllib.parse import urlencode, urlparse, parse_qs
from collections import deque
import time # Import the time module
import json
import re # Import the re module for regular expressions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


# Base URL for Google Scholar
GOOGLE_SCHOLAR_BASE_URL = "https://scholar.google.com/scholar"
GOOGLE_SCHOLAR_CITATIONS_BASE_URL = "https://scholar.google.com/citations"

# Default maximum number of articles to scrape if not overridden by inbound message
DEFAULT_MAX_NUMBER_OF_ARTICLES = 100
DEFAULT_NUM_RESULTS_PER_PAGE = 10 # Google Scholar typically shows 10 results per page

def _setup_driver(job_download_dir):
    """Configures and returns a headless Chrome WebDriver instance."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-crash-reporter")
    
    # Add a realistic User-Agent to mimic a regular browser
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36")
    # Set a window size to mimic a desktop browser
    chrome_options.add_argument("--window-size=1920,1080")

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

def _build_scholar_url(query_params, start_index=0):
    """
    Builds a Google Scholar search URL from the given query parameters.
    Maps our internal params to Google Scholar's URL parameters.
    """
    scholar_params = {}

    # Map our query parameters to Google Scholar's URL parameters
    if query_params.get("all_words"):
        scholar_params["q"] = query_params["all_words"]
    
    # Google Scholar uses intitle: for exact phrase in title, but for general exact phrase,
    # it's usually handled by quotes in the main 'q' parameter or a separate 'as_epq'
    # For simplicity, let's combine with 'q' using quotes if 'q' is not already set.
    # If 'q' is set, we'll use 'as_epq'
    if query_params.get("exact_phrase"):
        if "q" in scholar_params:
            scholar_params["as_epq"] = query_params["exact_phrase"]
        else:
            scholar_params["q"] = f'"{query_params["exact_phrase"]}"'

    if query_params.get("at_least_one"):
        scholar_params["as_oq"] = query_params["at_least_one"] # "with at least one of the words"

    if query_params.get("without_words"):
        scholar_params["as_eq"] = query_params["without_words"] # "without the words"

    if query_params.get("author"):
        scholar_params["as_sauthors"] = query_params["author"]

    if query_params.get("publication"):
        scholar_params["as_publication"] = query_params["publication"]

    date_range = query_params.get("date_range", {})
    if date_range.get("start_year"):
        scholar_params["as_ylo"] = date_range["start_year"]
    if date_range.get("end_year"):
        scholar_params["as_yhi"] = date_range["end_year"]

    if query_params.get("full_text_only"):
        # Google Scholar doesn't have a direct URL parameter for "full text only"
        # It's usually a checkbox on the advanced search page or implied by certain search terms.
        # We might need to interact with the advanced search form directly if this is critical.
        # For now, we'll omit it as a direct URL param.
        logging.warning("full_text_only is not directly supported via URL parameters for Google Scholar. This filter will be ignored.")

    if query_params.get("review_articles_only"):
        # Similar to full_text_only, this is not a direct URL param.
        logging.warning("review_articles_only is not directly supported via URL parameters for Google Scholar. This filter will be ignored.")

    # Add the start index for pagination
    if start_index > 0:
        scholar_params["start"] = start_index

    # Force English language interface
    scholar_params["hl"] = "en"

    # Construct the URL
    if not scholar_params: # Explicitly check if scholar_params is empty
        return GOOGLE_SCHOLAR_BASE_URL

    encoded_params = urlencode(scholar_params)
    return f"{GOOGLE_SCHOLAR_BASE_URL}?{encoded_params}"

def _get_scholar_profile_details(driver, scholar_user_id):
    """
    Navigates to a Google Scholar profile page and extracts organization and citation count.
    """
    logging.debug(f"Fetching scholar profile details for user ID: {scholar_user_id}")
    profile_url = f"{GOOGLE_SCHOLAR_CITATIONS_BASE_URL}?user={scholar_user_id}&hl=en"
    logging.info(f"Navigating to scholar profile URL: {profile_url}")
    
    original_window = driver.current_window_handle
    driver.execute_script("window.open('');")
    driver.switch_to.window(driver.window_handles[1])
    
    profile_details = {"scholar_org": None, "scholar_citations": None}
    try:
        driver.get(profile_url)
        time.sleep(2) # Give page time to load

        # Extract scholar_org
        try:
            org_element = driver.find_element(By.CSS_SELECTOR, 'div.gsc_prf_il a.gsc_prf_ila')
            profile_details["scholar_org"] = org_element.text.strip()
        except NoSuchElementException:
            logging.warning(f"Could not find scholar_org for user {scholar_user_id}")

        # Extract scholar_citations
        try:
            citations_table = driver.find_element(By.ID, 'gsc_rsb_st')
            # The second cell of the first row after the header (which is tbody > tr:nth-child(1) > td:nth-child(2))
            citations_element = citations_table.find_element(By.CSS_SELECTOR, 'tbody tr:nth-child(1) td:nth-child(2)')
            profile_details["scholar_citations"] = citations_element.text.strip()
        except NoSuchElementException:
            logging.warning(f"Could not find scholar_citations for user {scholar_user_id}")

    except Exception as e:
        logging.error(f"Error fetching profile details for {scholar_user_id}: {e}")
    finally:
        driver.close()
        driver.switch_to.window(original_window)
    
    return profile_details

def _parse_single_article(article_element, driver, fetch_author_details, author_profile_cache):
    """
    Parses a single Google Scholar article element and extracts relevant information.
    """
    title_element = article_element.find_element(By.CSS_SELECTOR, 'h3.gs_rt a')
    title = title_element.text
    link = title_element.get_attribute('href')

    snippet_element = article_element.find_element(By.CSS_SELECTOR, 'div.gs_rs')
    snippet = snippet_element.text

    author_info_container = article_element.find_element(By.CSS_SELECTOR, 'div.gs_a')
    
    authors_list = []
    publication_details_str = ""
    
    # Find all author links (scholar profiles)
    author_links = author_info_container.find_elements(By.CSS_SELECTOR, 'a[href*="citations?user="]')
    
    linked_author_names = set()

    for author_link in author_links:
        name = author_link.text.strip()
        linked_author_names.add(name)
        href = author_link.get_attribute('href')
        
        scholar_user = None
        try:
            parsed_url = urlparse(href)
            query_params = parse_qs(parsed_url.query)
            scholar_user = query_params.get('user', [None])[0]
        except Exception as e:
            logging.warning(f"Could not parse scholar user ID from link {href}: {e}")
        
        author_data = {
            "name": name,
            "scholar_user": scholar_user,
            "scholar_org": None,
            "scholar_citations": None
        }

        if fetch_author_details and scholar_user:
            if scholar_user not in author_profile_cache:
                profile_details = _get_scholar_profile_details(driver, scholar_user)
                author_profile_cache[scholar_user] = profile_details
            else:
                profile_details = author_profile_cache[scholar_user]
            
            author_data["scholar_org"] = profile_details["scholar_org"]
            author_data["scholar_citations"] = profile_details["scholar_citations"]
        
        authors_list.append(author_data)
    
    publication_info_elements = author_info_container.find_elements(By.CSS_SELECTOR, 'span.gs_a_ext')
    if publication_info_elements:
        publication_details_str = publication_info_elements[0].text.strip()

    full_text_in_container = author_info_container.text
    
    temp_text = full_text_in_container
    for name in linked_author_names:
        temp_text = temp_text.replace(name, '').strip()
    if publication_details_str:
        temp_text = temp_text.replace(publication_details_str, '').strip()
    
    temp_text = temp_text.replace(', ,', ',').replace(' - -', ' - ').strip(' ,-')

    if temp_text:
        unlinked_author_parts = [p.strip() for p in temp_text.replace(' and ', ',').split(',') if p.strip()]
        for part in unlinked_author_parts:
            if part not in linked_author_names:
                authors_list.append({
                    "name": part,
                    "scholar_user": None,
                    "scholar_org": None,
                    "scholar_citations": None
                })
    
    pdf_link = None
    pdf_link_elements = article_element.find_elements(By.CSS_SELECTOR, 'div.gs_ggs.gs_scl a')
    if pdf_link_elements:
        pdf_link = pdf_link_elements[0].get_attribute('href')

    return {
        "title": title,
        "link": link,
        "snippet": snippet,
        "authors": authors_list,
        "publication_details": publication_details_str,
        "pdf_link": pdf_link
    }


def _get_total_estimated_results(driver):
    """
    Extracts the total estimated number of results from the page.
    It searches the entire page source for the pattern "About X results (Y sec)"
    and then parses the number X.
    Returns 0 if the pattern is not found or parsing fails.
    """
    try:
        # Get the entire page source
        page_source = driver.page_source
        logging.debug(f"Searching for estimated results in page source (first 500 chars): '{page_source[:500]}...'")
        
        # Use regex to find the pattern "About X results (Y sec)"
        # X can have thousands separators (., or ,)
        # Y can also have thousands separators and be wrapped in HTML tags
        match = re.search(r'About\s+([\d.,]+)\s+results\s+\(.+?sec\)', page_source)
        if match:
            number_str = match.group(1)
            # Remove all non-digit characters (like . or , used as thousands separators)
            number_str = re.sub(r'[.,]', '', number_str)
            estimated_results = int(number_str)
            logging.debug(f"Parsed estimated results: {estimated_results}")
            return estimated_results
        else:
            logging.warning("Regex pattern 'About [\\d.,]+ results (.+?sec)' not found in the page source.")

    except Exception as e:
        logging.warning(f"Could not parse total estimated results: {e}")
    return 0


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Performs an advanced Google Scholar search based on the provided parameters,
    scrapes the results, and returns them in the outbound JSON message.
    """
    query_params = params.get('query', {})
    if not query_params:
        raise ValueError("'query' parameter is missing or empty for 'search_google_scholar'")

    fetch_author_details = params.get('fetch_author_details', False)
    max_articles = params.get('max_articles', DEFAULT_MAX_NUMBER_OF_ARTICLES)

    # Create a job-specific directory for driver logs and cache
    job_download_dir = os.path.join(download_dir, job_id)
    os.makedirs(job_download_dir, exist_ok=True)

    driver = None
    all_results = []
    start_index = 0 # Initialize start index for pagination
    total_estimated_results = float('inf') # Initialize with a very large number
    estimated = 0 # Initialize estimated to 0
    author_profile_cache = {} # Cache for author profile details

    try:
        driver = _setup_driver(job_download_dir)
        
        while len(all_results) < max_articles and start_index < total_estimated_results:
            
            search_url = _build_scholar_url(query_params, start_index)
            logging.info(f"Navigating to Google Scholar URL: {search_url}")
            driver.get(search_url)

            # Log the page source immediately after loading (first 2000 chars)
            logging.debug(f"Page source after navigating to URL:\n{driver.page_source[:2000]}...")

            # On the first page (start_index == 0), try to get the total estimated results
            if start_index == 0:
                estimated = _get_total_estimated_results(driver)
                if estimated > 0:
                    total_estimated_results = estimated
                    logging.info(f"Total estimated results found: {total_estimated_results}")
                else:
                    logging.info("Could not determine total estimated results, continuing without an upper bound from estimated results.")


            logging.info(f"Scraping results starting from index {start_index}...")
            
            # Get all article elements on the current page
            article_elements = driver.find_elements(By.CSS_SELECTOR, 'div.gs_r.gs_or.gs_scl')
            logging.info(f"Found {len(article_elements)} article elements on the page.")

            for i, article_element in enumerate(article_elements):
                if len(all_results) >= max_articles:
                    logging.debug(f"Max articles ({max_articles}) reached. Stopping processing current page.")
                    break # Stop processing if max_articles is reached

                try:
                    parsed_article = _parse_single_article(article_element, driver, fetch_author_details, author_profile_cache)
                    all_results.append(parsed_article)
                except Exception as e:
                    logging.warning(f"Error parsing article {i} on page {start_index}: {e}")
            
            logging.info(f"Total scraped so far: {len(all_results)}")

            if not article_elements or len(all_results) >= max_articles:
                logging.info("No more results found on this page or max_articles reached. Ending pagination.")
                break
            
            # Increment for next page
            start_index += DEFAULT_NUM_RESULTS_PER_PAGE

            # Add a small delay to avoid being too aggressive
            time.sleep(2) 
        
        result = {
            'job_id': job_id,
            'status': 'complete',
            'result': {
                'search_query': query_params,
                'total_results_scraped': len(all_results),
                'estimated_article_count': estimated,
                'articles': all_results
            }
        }

    except Exception as e:
        logging.error(f"An error occurred during Google Scholar search for job {job_id}: {e}", exc_info=True)
        result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}

    finally:
        if driver:
            driver.quit()
            time.sleep(1) # Give time for processes to release file handles
            if hasattr(driver, 'temp_dir'):
                try:
                    shutil.rmtree(driver.temp_dir)
                except OSError as e:
                    logging.warning(f"Could not remove temporary directory {driver.temp_dir}: {e}")
        # Clean up job-specific directory
        if os.path.exists(job_download_dir):
            try:
                shutil.rmtree(job_download_dir)
            except OSError as e:
                logging.warning(f"Could not remove job download directory {job_download_dir}: {e}")

    write_result_to_outbound(job_id, result)


if __name__ == '__main__':
    # This block allows the script to be run directly for testing purposes.
    import sys
    import uuid
    import json

    # Set logging level to INFO to see detailed messages
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Example usage:
    # python search_google_scholar.py '{"query": {"all_words": "large language models", "date_range": {"start_year": 2022}}}'
    # python search_google_scholar.py '{"query": {"exact_phrase": "reinforcement learning from human feedback", "author": "OpenAI"}}'
    # python search_google_scholar.py '{"query": {"all_words": "AI ethics"}, "max_articles": 5}'
    # python search_google_scholar.py '{"query": {"all_words": "AI ethics"}, "fetch_author_details": false, "max_articles": 2}'
    # Test case: fetch author details for 2 articles
    # python search_google_scholar.py '{"query": {"all_words": "machine learning"}, "fetch_author_details": true, "max_articles": 2}'
    # Test case: do not fetch author details for 2 articles
    # python search_google_scholar.py '{"query": {"all_words": "machine learning"}, "fetch_author_details": false, "max_articles": 2}'


    if len(sys.argv) < 2:
        print("Usage: python search_google_scholar.py <JSON_PARAMS_STRING>")
        sys.exit(1)

    try:
        test_params = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON params: {e}")
        sys.exit(1)

    test_job_id = f"test-scholar-job-{uuid.uuid4()}"
    test_download_dir = tempfile.gettempdir()

    def print_result_to_console(job_id, result):
        """A mock writer function that prints the result to the console."""
        print(json.dumps(result, indent=2))

    execute(test_job_id, test_params, test_download_dir, print_result_to_console)
