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
    chrome_options = get_chrome_options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-crash-reporter")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-in-process-stack-traces")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--disable-dev-tools")
    chrome_options.add_argument("--log-level=3")
    
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

def _build_scholar_url(query_params, start_index=0):
    """
    Builds a Google Scholar search URL from the given query parameters using the advanced search syntax.
    """
    scholar_params = {
        'as_q': query_params.get("all_words", ""),
        'as_epq': query_params.get("exact_phrase", ""),
        'as_oq': query_params.get("at_least_one", ""),
        'as_eq': query_params.get("without_words", ""),
        'as_occt': 'any',
        'as_sauthors': query_params.get("author", ""),
        'as_publication': query_params.get("publication", ""),
        'as_ylo': query_params.get("date_range", {}).get("start_year", ""),
        'as_yhi': query_params.get("date_range", {}).get("end_year", ""),
        'hl': 'en',
        'as_sdt': '0,5'
    }

    if query_params.get("full_text_only"):
        logging.warning("full_text_only is not directly supported via URL parameters for Google Scholar. This filter will be ignored.")

    if query_params.get("review_articles_only"):
        logging.warning("review_articles_only is not directly supported via URL parameters for Google Scholar. This filter will be ignored.")

    # Add the start index for pagination
    if start_index > 0:
        scholar_params["start"] = start_index

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

def _is_author_relevant(author_name, relevant_author_query):
    """
    Checks if an author's name from the search results is relevant to the queried author name.
    This function handles full names, initials, and variations in formatting.
    e.g., "Richard Handler" (query) should match "R Handler" (result).
    e.g., "Y. Martin" (query) should match "Yves-Loic Martin" (result).
    """
    if not relevant_author_query:
        return False

    # Normalize both names: lowercase, remove hyphens and periods.
    author_norm = author_name.lower().replace('-', ' ').replace('.', '')
    query_norm = relevant_author_query.lower().replace('-', ' ').replace('.', '')

    # Direct comparison for exact matches (e.g., "r handler" vs "r handler")
    if author_norm == query_norm:
        return True

    author_parts = author_norm.split()
    query_parts = query_norm.split()

    if not author_parts or not query_parts:
        return False

    # Last names must match.
    if author_parts[-1] != query_parts[-1]:
        return False

    # --- At this point, last names match. Now check first/middle names/initials. ---

    author_first_names = author_parts[:-1]
    query_first_names = query_parts[:-1]

    # If one has no first name parts, the other must also have no first name parts.
    if not author_first_names and not query_first_names:
        return True
    if not author_first_names or not query_first_names:
        return False

    # Check for initial-based.
    # This is bidirectional: works if the query has initials and the result has full names, or vice-versa.
    
    # Form the initial strings for both the author and the query.
    author_initials_str = "".join([name[0] for name in author_first_names])
    query_initials_str = "".join([name[0] for name in query_first_names])

    # Form the full first name strings.
    author_first_name_full_str = "".join(author_first_names)
    query_first_name_full_str = "".join(query_first_names)

    # Case 1: Query has initials, author has full name (e.g., query "r handler", author "richard handler")
    # This checks if the query's first name part(s) are the initials of the author's first name part(s).
    if query_first_name_full_str == author_initials_str:
        return True

    # Case 2: Author has initials, query has full name (e.g., query "richard handler", author "r handler")
    # This checks if the author's first name part(s) are the initials of the query's first name part(s).
    if author_first_name_full_str == query_initials_str:
        return True

    # Case 3: Partial match where one is a prefix of the other (e.g., "yves" vs "yves loic")
    # This is useful for cases where a middle name is omitted.
    if " ".join(author_first_names).startswith(" ".join(query_first_names)) or \
       " ".join(query_first_names).startswith(" ".join(author_first_names)):
        return True

    return False

def _parse_single_article(article_element, driver, fetch_author_details, relevant_author_query, author_profile_cache):
    """
    Parses a single Google Scholar article element and extracts relevant information.
    """
    title_element = article_element.find_element(By.CSS_SELECTOR, 'h3.gs_rt a')
    title = title_element.text
    link = title_element.get_attribute('href')

    snippet_element = article_element.find_element(By.CSS_SELECTOR, 'div.gs_rs')
    snippet = snippet_element.text

    author_info_container = article_element.find_element(By.CSS_SELECTOR, 'div.gs_a')
    raw_author_line = author_info_container.text
    
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

        should_fetch = (fetch_author_details == 'all') or \
                       (fetch_author_details == 'relevant' and _is_author_relevant(name, relevant_author_query))

        if should_fetch and scholar_user:
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
        "raw_author_line": raw_author_line,
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
    logging.info(f"Executing search_google_scholar for job {job_id} with params: {json.dumps(params, indent=2)}")

    query_params = params.get('query', {})
    if not query_params:
        raise ValueError("'query' parameter is missing or empty for 'search_google_scholar'")

    fetch_author_details = params.get('fetch_author_details', 'none') # 'none', 'all', 'relevant'
    max_articles = params.get('max_number_of_articles', DEFAULT_MAX_NUMBER_OF_ARTICLES)
    relevant_author_query = query_params.get('author') if fetch_author_details == 'relevant' else None

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

            # **FIX**: Handle author-only search results which might land on a profile page.
            # If the query is primarily an author search and no other major filters are present,
            # Google Scholar may show a list of author profiles instead of articles.
            is_author_only_search = query_params.get("author") and not (query_params.get("all_words") or query_params.get("exact_phrase"))
            if start_index == 0 and is_author_only_search:
                try:
                    # Look for the main author profile link on the page
                    author_profile_link = driver.find_element(By.CSS_SELECTOR, 'h3.gs_rt a[href*="/citations?user="]')
                    profile_url = author_profile_link.get_attribute('href')
                    logging.info(f"Author-only search detected. Found author profile page. Navigating to full publication list: {profile_url}")
                    driver.get(profile_url)
                    # After navigating, wait for the "Show more" button to ensure the article list is loaded.
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "gsc_bpf_more")))
                    logging.info("Successfully navigated to author's full publication page.")
                except (NoSuchElementException, TimeoutException):
                    # If the element isn't found, it's likely a normal search results page. Proceed as usual.
                    logging.info("Author-only search did not lead to a profile page, or profile page was not found. Proceeding with standard scraping.")

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
                    parsed_article = _parse_single_article(article_element, driver, fetch_author_details, relevant_author_query, author_profile_cache)
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

    logging.info(f"Sending result for job {job_id}: {json.dumps(result, indent=2)}")
    write_result_to_outbound(job_id, result)


if __name__ == '__main__':
    # This block allows the script to be run directly for testing purposes.
    import sys
    import uuid
    import json

    # Set logging level to INFO to see detailed messages printed to the console.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Example usage:
    # python src\actions\search_google_scholar.py '{""query"": {""all_words"": ""large language models"", ""date_range"": {""start_year"": 2022}}}'
    # python src\actions\search_google_scholar.py '{""query"": {""exact_phrase"": ""reinforcement learning from human feedback"", ""author"": ""OpenAI""}}'
    # python src\actions\search_google_scholar.py '{""query"": {""all_words": ""AI ethics""}, ""max_articles"": 5}'
    # python src\actions\search_google_scholar.py '{""query"": {""all_words": ""AI ethics""}, ""fetch_author_details"": ""none"", ""max_articles"": 2}'
    # Test case: fetch all author details for 2 articles
    # python src\actions\search_google_scholar.py '{""query"": {""all_words"": ""machine learning""}, ""fetch_author_details"": ""all"", ""max_articles"": 2}'
    # Test case: fetch relevant author details for 2 articles
    # python src\actions\search_google_scholar.py '{""query"": {""author"": ""Richard Handler"", ""all_words"": ""authenticity""}, ""fetch_author_details"": ""relevant"", ""max_articles"": 10}'

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
