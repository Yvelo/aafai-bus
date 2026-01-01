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
from urllib.parse import urlencode, urljoin
import time
import json
import re
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

# Base URL for Semantic Scholar
SEMANTIC_SCHOLAR_BASE_URL = "https://www.semanticscholar.org/search"

# Default maximum number of articles to scrape if not overridden by inbound message
DEFAULT_MAX_NUMBER_OF_ARTICLES = 1000
DEFAULT_NUM_RESULTS_PER_PAGE = 10  # Semantic Scholar shows 10 results per page


def _setup_driver(job_download_dir, download_dir):
    """Configures and returns a headless Chrome WebDriver instance."""
    chrome_options = Options()
    if os.environ.get('HEADLESS_BROWSER', 'true').lower() == 'true':
        chrome_options.add_argument("--headless=new")
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

    # Anti-scraping measures
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    temp_dir = tempfile.mkdtemp()
    os.environ['HOME'] = temp_dir

    user_data_dir = os.path.join(temp_dir, "user-data")
    disk_cache_dir = os.path.join(temp_dir, "cache")
    crash_dumps_dir = os.path.join(temp_dir, "crash-dumps")

    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_options.add_argument(f"--disk-cache-dir={disk_cache_dir}")
    chrome_options.add_argument(f"--crash-dumps-dir={crash_dumps_dir}")

    driver_cache_dir = os.path.join(download_dir, "driver_cache")
    os.makedirs(driver_cache_dir, exist_ok=True)

    chromedriver_log_path = os.path.join(job_download_dir, "chromedriver.log")
    service = Service(ChromeDriverManager(cache_manager=DriverCacheManager(root_dir=driver_cache_dir)).install(), service_args=['--verbose', f'--log-path={chromedriver_log_path}'])

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)
    driver.temp_dir = temp_dir
    return driver


def _build_semantic_scholar_url(query_params):
    """Builds a Semantic Scholar search URL from the given query parameters for the first page."""
    query_parts = []
    if query_params.get("all_words"):
        query_parts.append(query_params["all_words"])
    if query_params.get("exact_phrase"):
        query_parts.append(f'"{query_params["exact_phrase"]}"')

    if query_params.get("author"):
        query_parts.append(query_params["author"])

    if query_params.get("at_least_one"):
        query_parts.append(f'({query_params["at_least_one"]})')
    if query_params.get("without_words"):
        exclusions = " ".join([f"-{word.strip()}" for word in query_params["without_words"].split()])
        query_parts.append(exclusions)

    search_query = " ".join(query_parts)
    params = {'q': search_query, 'sort': 'relevance'}

    date_range = query_params.get("date_range", {})
    start_year = date_range.get("start_year")
    end_year = date_range.get("end_year")
    if start_year and end_year:
        params['year'] = f"{start_year}-{end_year}"
    elif start_year:
        params['year'] = f"{start_year}-"
    elif end_year:
        params['year'] = f"-{end_year}"

    encoded_params = urlencode(params)
    return f"{SEMANTIC_SCHOLAR_BASE_URL}?{encoded_params}"


def _get_author_details(driver, author_url):
    """Navigates to a Semantic Scholar author page and extracts details."""
    logging.debug(f"Fetching author details from URL: {author_url}")
    original_window = driver.current_window_handle
    driver.execute_script("window.open('');")
    driver.switch_to.window(driver.window_handles[-1])
    details = {"affiliation": None, "total_citations": None, "h_index": None}
    try:
        driver.get(author_url)
        time.sleep(2)
        try:
            details["affiliation"] = driver.find_element(By.CSS_SELECTOR, 'ul[data-test-id="author-affiliations"] li').text.strip()
        except NoSuchElementException:
            logging.warning(f"Could not find affiliation for author at {author_url}")
        stats_elements = driver.find_elements(By.CSS_SELECTOR, '.author-detail-card__stats-row .author-detail-card__stats-value')
        if len(stats_elements) >= 3:
            details["total_citations"] = stats_elements[0].text.strip()
            details["h_index"] = stats_elements[2].text.strip()
    except Exception as e:
        logging.error(f"Error fetching author details from {author_url}: {e}")
    finally:
        driver.close()
        driver.switch_to.window(original_window)
    return details


def _is_author_relevant(author_name, relevant_author_query):
    """Checks if an author's name from the search results is relevant to the queried author name."""
    if not relevant_author_query:
        return False
    author_norm = author_name.lower().replace('-', ' ').replace('.', '')
    query_norm = relevant_author_query.lower().replace('-', ' ').replace('.', '')
    if author_norm == query_norm:
        return True
    author_parts = author_norm.split()
    query_parts = query_norm.split()
    if not author_parts or not query_parts or author_parts[-1] != query_parts[-1]:
        return False
    author_first_names = author_parts[:-1]
    query_first_names = query_parts[:-1]
    if not author_first_names and not query_first_names:
        return True
    if not author_first_names or not query_first_names:
        return False
    author_initials_str = "".join([name[0] for name in author_first_names])
    query_initials_str = "".join([name[0] for name in query_first_names])
    author_first_name_full_str = "".join(author_first_names)
    query_first_name_full_str = "".join(query_first_names)
    if query_first_name_full_str == author_initials_str or author_first_name_full_str == query_initials_str:
        return True
    return " ".join(author_first_names).startswith(" ".join(query_first_names)) or \
           " ".join(query_first_names).startswith(" ".join(author_first_names))


def _parse_single_article(article_element, driver, fetch_author_details, relevant_author_query, author_profile_cache):
    """Parses a single Semantic Scholar article element."""
    try:
        title_element = article_element.find_element(By.CSS_SELECTOR, 'a[data-test-id="title-link"]')
        title = title_element.text
        link = title_element.get_attribute('href')
    except NoSuchElementException:
        title, link = None, None
    try:
        snippet_element = article_element.find_element(By.CSS_SELECTOR, 'div.tldr-abstract-replacement > span')
        snippet = snippet_element.text
    except NoSuchElementException:
        snippet = None
    authors_list = []
    try:
        author_elements = article_element.find_elements(By.CSS_SELECTOR, 'span[data-test-id="author-list"] a')
        for author_element in author_elements:
            name = author_element.text.strip()
            author_url = author_element.get_attribute('href')
            author_data = {"name": name, "author_url": author_url}
            should_fetch = (fetch_author_details == 'all') or (fetch_author_details == 'relevant' and _is_author_relevant(name, relevant_author_query))
            if should_fetch and author_url:
                if author_url not in author_profile_cache:
                    author_profile_cache[author_url] = _get_author_details(driver, author_url)
                
                profile_details = author_profile_cache.get(author_url, {})
                # Only add details if they are not null
                for key, value in profile_details.items():
                    if value is not None:
                        author_data[key] = value

            authors_list.append(author_data)
    except NoSuchElementException:
        pass
    publication_details = None
    parts = []
    try:
        parts.append(article_element.find_element(By.CSS_SELECTOR, '[data-test-id="venue-metadata"]').text)
    except NoSuchElementException:
        pass
    try:
        parts.append(article_element.find_element(By.CSS_SELECTOR, 'span.cl-paper-pubdates').text)
    except NoSuchElementException:
        pass
    if parts:
        publication_details = " ".join(parts)
    pdf_link = None
    try:
        pdf_link = article_element.find_element(By.CSS_SELECTOR, 'a[data-test-id="paper-link"]').get_attribute('href')
    except NoSuchElementException:
        pass
    citations = 0
    try:
        citation_text = article_element.find_element(By.CSS_SELECTOR, '[data-test-id="total-citations-stat"] .cl-paper-stats__v2-citations').text.strip().replace(',', '')
        if citation_text.isdigit():
            citations = int(citation_text)
    except (NoSuchElementException, ValueError):
        pass
    return {"title": title, "link": link, "snippet": snippet, "authors": authors_list, "publication_details": publication_details, "pdf_link": pdf_link, "citations": citations}


def _get_total_estimated_results(driver):
    """Extracts the total estimated number of results from the page."""
    try:
        results_header = driver.find_element(By.CSS_SELECTOR, 'div.dropdown-filters__result-count')
        match = re.search(r'([\d,]+)', results_header.text)
        if match:
            return int(match.group(1).replace(',', ''))
    except (NoSuchElementException, ValueError) as e:
        logging.warning(f"Could not parse total estimated results from header: {e}")
    return 0


def _extract_matched_authors(driver):
    """Extracts author information from the 'matched author' section."""
    authors = []
    try:
        author_cards = driver.find_elements(By.CSS_SELECTOR, '.matched-author-shoveler__list-item')
        for card in author_cards:
            try:
                name = card.find_element(By.CSS_SELECTOR, '[data-test-id="matched-author-link-name"]').text
                url = card.find_element(By.CSS_SELECTOR, 'a.matched-author-shoveler__author-link').get_attribute('href')
                metadata_items = card.find_elements(By.CSS_SELECTOR, '.matched-author-shoveler__metadata__item')
                publications_text = metadata_items[0].text if len(metadata_items) > 0 else "0"
                citations_text = metadata_items[1].text if len(metadata_items) > 1 else "0"
                publications = int(re.search(r'([\d,]+)', publications_text).group(1).replace(',', '')) if re.search(r'([\d,]+)', publications_text) else 0
                citations = int(re.search(r'([\d,]+)', citations_text).group(1).replace(',', '')) if re.search(r'([\d,]+)', citations_text) else 0
                authors.append({"name": name, "author_url": url, "publications": publications, "citations": citations})
            except (NoSuchElementException, ValueError) as e:
                logging.warning(f"Could not parse a matched author card: {e}")
    except NoSuchElementException:
        logging.info("No matched author section found.")
    return authors


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Performs a Semantic Scholar search based on the provided parameters,
    scrapes the results, and returns them in the outbound JSON message.
    """
    logging.info(f"Executing search_semantic_scholar for job {job_id} with params: {json.dumps(params, indent=2)}")
    query_params = params.get('query', {})
    if not query_params:
        raise ValueError("'query' parameter is missing or empty for 'search_semantic_scholar'")
    fetch_author_details = params.get('fetch_author_details', 'none')
    max_articles = params.get('max_number_of_articles', DEFAULT_MAX_NUMBER_OF_ARTICLES)
    relevant_author_query = query_params.get('author') if fetch_author_details == 'relevant' else None
    job_download_dir = os.path.join(download_dir, job_id)
    os.makedirs(job_download_dir, exist_ok=True)
    driver = None
    all_results = []
    matched_authors = []
    page = 1
    total_estimated_results = float('inf')
    estimated_articles = 0
    estimated_citations = 0
    author_profile_cache = {}
    try:
        driver = _setup_driver(job_download_dir, download_dir)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        search_url = _build_semantic_scholar_url(query_params)
        logging.info(f"Navigating to Semantic Scholar URL: {search_url}")
        driver.get(search_url)
        time.sleep(2)
        while len(all_results) < max_articles:
            if page == 1:
                estimated_from_header = _get_total_estimated_results(driver)
                if estimated_from_header > 0:
                    total_estimated_results = estimated_from_header
                    logging.info(f"Total estimated results found from header: {total_estimated_results}")
                
                if query_params.get("author"):
                    matched_authors = _extract_matched_authors(driver)
                    if matched_authors:
                        estimated_articles = sum(author.get('publications', 0) for author in matched_authors)
                        estimated_citations = sum(author.get('citations', 0) for author in matched_authors)
                        logging.info(f"Total estimated articles from matched authors: {estimated_articles}")
                        logging.info(f"Total estimated citations from matched authors: {estimated_citations}")
                    else:
                        estimated_articles = estimated_from_header
                else:
                    estimated_articles = estimated_from_header

            logging.info(f"Scraping results from page {page}...")
            article_elements = driver.find_elements(By.CSS_SELECTOR, 'div.cl-paper-row')
            logging.info(f"Found {len(article_elements)} article elements on the page.")
            if not article_elements:
                logging.info("No more results found. Ending pagination.")
                break
            for i, article_element in enumerate(article_elements):
                if len(all_results) >= max_articles:
                    break
                try:
                    parsed_article = _parse_single_article(article_element, driver, fetch_author_details, relevant_author_query, author_profile_cache)
                    if parsed_article.get("title"):
                        all_results.append(parsed_article)
                except Exception as e:
                    logging.warning(f"Error parsing article {i} on page {page}: {e}", exc_info=True)
            logging.info(f"Total scraped so far: {len(all_results)}")
            if len(all_results) >= max_articles or len(all_results) >= total_estimated_results:
                logging.info("Max articles or estimated total reached. Ending pagination.")
                break
            try:
                next_button = driver.find_element(By.CSS_SELECTOR, 'button[data-test-id="next-page"]')
                if not next_button.is_enabled():
                    logging.info("Next page button is disabled. Ending pagination.")
                    break
                driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
                time.sleep(0.5)
                next_button.click()
                page += 1
                time.sleep(3.5)
            except (NoSuchElementException, ElementClickInterceptedException):
                logging.info("No next page button found or it was not clickable. Ending pagination.")
                break
        all_results.sort(key=lambda x: x.get('citations', 0), reverse=True)
        result = {'job_id': job_id, 'status': 'complete', 'result': {'search_query': query_params, 'total_results_scraped': len(all_results), 'estimated_article_count': estimated_articles, 'estimated_citation_count': estimated_citations, 'matched_authors': matched_authors, 'articles': all_results}}
    except Exception as e:
        logging.error(f"An error occurred during Semantic Scholar search for job {job_id}: {e}", exc_info=True)
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
        print("Usage: python search_semantic_scholar.py <JSON_PARAMS_STRING>")
        sys.exit(1)
    try:
        test_params = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON params: {e}")
        sys.exit(1)
    test_job_id = f"test-semantic-scholar-job-{uuid.uuid4()}"
    test_download_dir = tempfile.gettempdir()
    def print_result_to_console(job_id, result):
        print(json.dumps(result, indent=2))
    execute(test_job_id, test_params, test_download_dir, print_result_to_console)
