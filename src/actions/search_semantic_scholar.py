import logging
import os
import shutil
import sys
from unittest.mock import MagicMock
from src.browser_config import get_headless_status

# BEGIN: Monkey patch for distutils
# This is required for undetected-chromedriver to work with Python 3.12+
if sys.version_info >= (3, 12):
    try:
        import packaging.version

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

from selenium_stealth import stealth
from selenium.webdriver.common.by import By
import tempfile
from urllib.parse import urlencode, urljoin
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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
    """Configures and returns a Chrome WebDriver instance using undetected-chromedriver."""
    temp_dir = tempfile.mkdtemp()
    os.environ['HOME'] = temp_dir

    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    is_headless = get_headless_status()

    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')
    options.add_argument('--profile-directory=Default')
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--lang=en-US")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-crash-reporter")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-in-process-stack-traces")
    options.add_argument("--disable-logging")
    options.add_argument("--disable-dev-tools")
    options.add_argument("--log-level=3")
    options.add_argument("--window-size=1920, 1080")

    try:
        # First attempt: let undetected-chromedriver auto-detect the installed Chrome version
        driver = uc.Chrome(
            options=options,
            headless=is_headless
        )
    except Exception as e:
        # Fallback: if auto-detection failed due to version mismatch, parse the browser version from error if possible
        version_match = re.search(r'Current browser version is (\d+)', str(e))
        if version_match:
            detected_version = int(version_match.group(1))
            logging.info(f"Retrying undetected_chromedriver with detected Chrome version {detected_version}")
            driver = uc.Chrome(
                options=options,
                headless=is_headless,
                version_main=detected_version
            )
        else:
            raise

    if is_headless:
        stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

    driver.set_page_load_timeout(60)
    driver.temp_dir = temp_dir
    return driver


def _handle_security_check(driver, timeout=90):
    """
    Checks if an AWS WAF CAPTCHA / bot challenge page is displayed.
    Automatically clicks 'Begin' (#amzn-captcha-verify-button) if present to open the interactive puzzle.
    In non-headless mode, waits for the user to complete the puzzle until the page redirects back.
    In headless mode, raises an exception.
    """
    bot_indicators = [
        "Complete the security check before continuing",
        "verifies that you are not a bot",
        "confirm you are human",
        "verify you are human",
        "captcha-container",
        "amzn-captcha",
        "AwsWafIntegration",
    ]
    try:
        page_source = driver.page_source or ""
        if any(ind.lower() in page_source.lower() for ind in bot_indicators):
            logging.warning("AWS WAF CAPTCHA / security check detected on Semantic Scholar.")

            # Attempt to click the 'Begin' button if it's there to display the puzzle
            try:
                begin_button = driver.find_element(By.ID, "amzn-captcha-verify-button")
                if begin_button.is_displayed():
                    logging.info("Found 'Begin' button for AWS WAF CAPTCHA. Clicking it to reveal puzzle...")
                    driver.execute_script("arguments[0].click();", begin_button)
                    time.sleep(2)
            except NoSuchElementException:
                pass
            except Exception as e:
                logging.debug(f"Could not click 'Begin' button: {e}")

            if not get_headless_status():
                logging.info(f"Running in non-headless mode: waiting up to {timeout}s for CAPTCHA to be solved...")
                # Wait until none of the bot challenge indicators remain in page source or container is gone
                WebDriverWait(driver, timeout, poll_frequency=2).until_not(
                    lambda d: ("captcha-container" in (d.page_source or "") or
                               "confirm you are human" in (d.page_source or "").lower() or
                               "verifies that you are not a bot" in (d.page_source or "").lower())
                )
                logging.info("CAPTCHA / Security check resolved successfully.")
                time.sleep(3)
            else:
                raise RuntimeError("Semantic Scholar blocked the request with AWS WAF CAPTCHA (headless mode).")
    except TimeoutException:
        raise RuntimeError(f"Timed out waiting {timeout}s for AWS WAF CAPTCHA to be resolved.")
    except Exception as e:
        if "blocked the request" in str(e) or "Timed out waiting" in str(e):
            raise
        logging.warning(f"Error checking for security popup: {e}")


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
    details = {
        "affiliation": None,
        "publications": None,
        "h_index": None,
        "total_citations": None,
        "highly_influential_citations": None
    }
    try:
        driver.get(author_url)
        time.sleep(2)
        try:
            details["affiliation"] = driver.find_element(By.CSS_SELECTOR, 'ul[data-test-id="author-affiliations"] li').text.strip()
        except NoSuchElementException:
            logging.warning(f"Could not find affiliation for author at {author_url}")

        stats_rows = driver.find_elements(By.CSS_SELECTOR, '.author-detail-card__stats-row')
        for row in stats_rows:
            try:
                label_element = row.find_element(By.CSS_SELECTOR, '.author-detail-card__stats-row__label')
                label = label_element.text.strip()
                value_str = row.find_element(By.CSS_SELECTOR, '.author-detail-card__stats-row__value').text.strip()
                try:
                    value = int(value_str.replace(',', ''))
                except ValueError:
                    value = value_str

                if label == 'Publications':
                    details['publications'] = value
                elif label == 'h-index':
                    details['h_index'] = value
                elif label == 'Citations':
                    details['total_citations'] = value
                elif label == 'Highly Influential Citations':
                    details['highly_influential_citations'] = value
            except NoSuchElementException:
                logging.warning(f"Could not parse a stat row on author page {author_url}")
                continue

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

        search_url = _build_semantic_scholar_url(query_params)
        logging.info(f"Navigating to Semantic Scholar URL: {search_url}")
        try:
            driver.get(search_url)
        except TimeoutException:
            logging.warning("Initial page load timed out. The page might be partially loaded.")

        # Check for bot challenge / security verification
        _handle_security_check(driver)

        # Handle cookie banner if it appears
        try:
            wait = WebDriverWait(driver, 5)
            cookie_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-test-id="cookie-banner__dismiss-btn"]')))
            logging.info("Cookie banner found. Clicking 'ACCEPT & CONTINUE'.")
            cookie_button.click()
            time.sleep(2)  # Give a moment for the banner to disappear
        except TimeoutException:
            logging.info("Cookie banner not found or not clickable within the timeout period.")

        # Re-check in case security check pops up after cookie banner dismissal
        _handle_security_check(driver)

        while len(all_results) < max_articles:
            if page == 1:
                estimated_from_header = _get_total_estimated_results(driver)
                if estimated_from_header > 0:
                    total_estimated_results = estimated_from_header
                    logging.info(f"Total estimated results found from header: {total_estimated_results}")
                
                if query_params.get("author"):
                    matched_authors = _extract_matched_authors(driver)
                    if matched_authors:
                        if fetch_author_details != 'none':
                            logging.info(f"Fetching details for {len(matched_authors)} matched authors.")
                            for author in matched_authors:
                                author_url = author.get("author_url")
                                if author_url:
                                    if author_url not in author_profile_cache:
                                        should_fetch = (fetch_author_details == 'all') or \
                                                       (fetch_author_details == 'relevant' and _is_author_relevant(author.get('name', ''), relevant_author_query))
                                        if should_fetch:
                                            details = _get_author_details(driver, author_url)
                                            author_profile_cache[author_url] = details
                                        else:
                                            author_profile_cache[author_url] = {}
                                    details = author_profile_cache.get(author_url, {})
                                    author.update(details)
                        estimated_articles = sum(author.get('publications') or 0 for author in matched_authors)
                        estimated_citations = sum(author.get('total_citations') or author.get('citations') or 0 for author in matched_authors)
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
                time.sleep(1)
                next_button.click()
                page += 1
                time.sleep(5)
                _handle_security_check(driver)
            except (NoSuchElementException, ElementClickInterceptedException):
                logging.info("No next page button found or it was not clickable. Ending pagination.")
                break
        all_results.sort(key=lambda x: x.get('citations', 0), reverse=True)
        result = {'job_id': job_id, 'status': 'Completed', 'result': {'search_query': query_params, 'total_results_scraped': len(all_results), 'estimated_article_count': estimated_articles, 'estimated_citation_count': estimated_citations, 'matched_authors': matched_authors, 'articles': all_results}}
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
