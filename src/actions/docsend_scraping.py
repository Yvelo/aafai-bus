# -*- coding: utf-8 -*-
"""
Action: docsend_scraping

This action automates the process of downloading a presentation from a DocSend link.
It handles the email authentication, captures each slide, and compiles them into a single PDF.
"""

import os
import time
import re
import base64
import shutil
import tempfile
import logging
from time import sleep

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from src.browser_config import get_chrome_options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.common.keys import Keys # Import Keys
from selenium.webdriver.common.action_chains import ActionChains
import requests
from PIL import Image
from io import BytesIO


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Main entry point for the docsend_scraping action.
    """
    url = params.get('url')
    user_email = params.get('user_email')
    document_name = params.get('document_name', 'scraped_document')
    result = {}

    if not all([url, user_email]):
        result = {"job_id": job_id, "status": "failed", "error": "Missing required parameters: url or user_email."}
        write_result_to_outbound(job_id, result)
        return

    output_pdf_path = os.path.join(download_dir, f"{document_name}.pdf")

    driver = None
    service = None
    try:
        driver, service = _setup_driver(download_dir)

        _navigate_and_authenticate(driver, url, user_email)
        _handle_overlays(driver) # Handle overlays once after navigation
        time.sleep(2) # Add a delay after handling overlays

        _wait_for_viewer(driver)

        # Capture every page of the document by navigating from slide to slide
        captured_slides = _capture_all_slides(driver)

        if captured_slides:
            _compile_pdf(captured_slides, output_pdf_path)
            with open(output_pdf_path, "rb") as pdf_file:
                encoded_string = base64.b64encode(pdf_file.read()).decode('utf-8')
            result = {
                "job_id": job_id,
                "status": "Completed",
                "result": {
                    "downloaded_files": [
                        {
                            "filename": os.path.basename(output_pdf_path),
                            "path": output_pdf_path,
                            "size_bytes": os.path.getsize(output_pdf_path),
                            "text": "PDF content is image-based and cannot be extracted as text.",
                            "content_base64": encoded_string
                        }
                    ]
                }
            }
        else:
            result = {"job_id": job_id, "status": "failed", "error": "No slides were captured."}

    except Exception as e:
        logging.error(f"An error occurred during DocSend scraping: {e}")
        if driver and download_dir:
            error_screenshot_path = os.path.join(download_dir, 'error_screenshot.png')
            driver.save_screenshot(error_screenshot_path)
            logging.info(f"Saved error screenshot to {error_screenshot_path}")
        result = {"job_id": job_id, "status": "failed", "error": str(e)}

    finally:
        if driver:
            driver.quit()
            logging.info("\nWebDriver closed.")
        if service:
            service.stop()
        time.sleep(1)
        if driver and hasattr(driver, 'temp_dir'):
            try:
                shutil.rmtree(driver.temp_dir)
            except OSError as e:
                logging.warning(f"Warning: Could not remove temporary directory {driver.temp_dir}: {e}")
        if result:
            write_result_to_outbound(job_id, result)


def _setup_driver(download_dir):
    """Sets up the Selenium WebDriver."""
    options = get_chrome_options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')  # Set window size for consistency
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")
    options.add_experimental_option('excludeSwitches', ['enable-automation'])

    persistent_cache_dir = os.path.join(tempfile.gettempdir(), ".aafai-bus-cache", "drivers")
    os.makedirs(persistent_cache_dir, exist_ok=True)

    temp_dir = tempfile.mkdtemp()
    os.environ['HOME'] = temp_dir
    user_data_dir = os.path.join(temp_dir, "user-data")
    options.add_argument(f"--user-data-dir={user_data_dir}")

    chromedriver_log_path = os.path.join(download_dir, "chromedriver.log")
    service = Service(ChromeDriverManager(cache_manager=DriverCacheManager(root_dir=persistent_cache_dir)).install(),
                      service_args=['--verbose', f'--log-path={chromedriver_log_path}'])

    logging.info("Initializing WebDriver...")
    driver = webdriver.Chrome(service=service, options=options)
    driver.temp_dir = temp_dir
    return driver, service


def _navigate_and_authenticate(driver, url, email_address):
    """Navigates to the URL and handles the email submission form."""
    logging.info(f"Navigating to: {url}")
    driver.get(url)

    try:
        email_input = WebDriverWait(driver, 15).until(
            expected_conditions.visibility_of_element_located((By.ID, "link_auth_form_email"))
        )
        logging.info(f"Entering email address: {email_address}")
        email_input.send_keys(email_address)

        submit_button = WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable((By.CLASS_NAME, "js-auth-form_submit-button"))
        )
        submit_button.click()
        logging.info("Submitted email. Waiting for presentation viewer...")
    except TimeoutException:
        logging.info("Email submission form not found. Assuming public access.")
    except ElementClickInterceptedException:
        logging.warning("Initial click failed, retrying after handling overlays again.")
        _handle_overlays(driver)
        submit_button = WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable((By.CLASS_NAME, "js-auth-form_submit-button"))
        )
        driver.execute_script("arguments[0].click();", submit_button)
        logging.info("Submitted email with JS click. Waiting for presentation viewer...")


def _wait_for_viewer(driver):
    """Waits for the presentation viewer to load."""
    # The viewer is loaded when the carousel-inner is present and has a certain height
    try:
        WebDriverWait(driver, 20).until(
            expected_conditions.presence_of_element_located((By.CSS_SELECTOR, ".carousel-inner.js-carousel-inner"))
        )
        logging.info("Presentation viewer loaded.")
    except TimeoutException as e:
        logging.error("Presentation viewer did not load in time.")
        raise e


def _handle_overlays(driver):
    """Handles potential overlays like cookie banners using a robust JS click."""
    try:
        cookie_iframe = WebDriverWait(driver, 10).until(
            expected_conditions.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='ccpa_iframe']"))
        )
        driver.switch_to.frame(cookie_iframe)
        logging.info("Switched to cookie banner iframe.")

        robust_button_xpath = "//button[contains(., 'Accept all') or contains(., 'Accept All') or contains(., 'Tout accepter')]"
        accept_button = WebDriverWait(driver, 10).until(
            expected_conditions.presence_of_element_located((By.XPATH, robust_button_xpath))
        )
        
        logging.info("Attempting to click 'Accept all' on cookie banner with JS.")
        driver.execute_script("arguments[0].click();", accept_button)
        logging.info("Successfully clicked 'Accept all' on cookie banner with JS.")
        
        time.sleep(1)
    except TimeoutException:
        logging.info("No cookie banner found or it was not interactable within the timeout.")
    finally:
        driver.switch_to.default_content()
        logging.info("Switched focus back to the main page.")


def _capture_all_slides(driver):
    """
    Captures every page of the document by navigating from slide to slide.
    Returns a list of PIL Image objects, one per page.
    """
    total_slides = _get_total_slides_count(driver)
    if not total_slides:
        total_slides = _count_carousel_items(driver) or 1

    # Some documents are rendered in a vertically scrolling viewer where every page
    # image is already part of the DOM. In that case all pages can be downloaded directly.
    slides = _capture_all_page_images(driver, total_slides)
    if slides:
        logging.info(f"Finished capturing slides. Total: {len(slides)}")
        return slides

    logging.info(f"\nStarting capture of {total_slides} slides...")
    slides = []

    for page_number in range(1, total_slides + 1):
        slide_image = _capture_current_slide(driver, page_number)
        if slide_image is not None:
            slides.append(slide_image)
            logging.info(f"Captured slide {page_number}/{total_slides}.")
        else:
            logging.warning(f"Could not capture slide {page_number}/{total_slides}.")

        if page_number < total_slides:
            if not _go_to_next_slide(driver, page_number):
                logging.warning(f"Could not navigate past slide {page_number}. Stopping capture.")
                break

    logging.info(f"Finished capturing slides. Total: {len(slides)}")
    return slides


def _capture_all_page_images(driver, total_slides):
    """
    Tries to download every page image directly from the DOM (vertical viewer layout).
    Returns a list of PIL Images, or an empty list when the layout does not expose all pages.
    """
    image_urls = _collect_page_image_urls(driver)
    if len(image_urls) < total_slides:
        _scroll_viewer_to_load_all_pages(driver)
        image_urls = _collect_page_image_urls(driver)

    if not image_urls or len(image_urls) < total_slides:
        return []

    logging.info(f"All {len(image_urls)} page images are available in the viewer. Downloading them directly...")
    slides = []
    for page_number, image_url in enumerate(image_urls[:total_slides], start=1):
        image = _download_image(driver, image_url)
        if image is None:
            logging.warning(f"Could not download page image {page_number}. Falling back to slide navigation.")
            return []
        slides.append(image)
        logging.info(f"Captured slide {page_number}/{total_slides}.")
    return slides


def _collect_page_image_urls(driver):
    """Returns the source URLs of all loaded page images, in document order."""
    try:
        return driver.execute_script(
            "return Array.from(document.querySelectorAll('img.page-view'))"
            "  .filter(function (img) { return img.complete && img.naturalWidth > 0; })"
            "  .map(function (img) { return img.currentSrc || img.src; })"
            "  .filter(function (src) { return !!src; });"
        ) or []
    except Exception:
        return []


def _scroll_viewer_to_load_all_pages(driver):
    """Scrolls the vertical viewer to the bottom so that lazily loaded page images are fetched."""
    try:
        container = driver.find_element(By.CSS_SELECTOR, ".carousel-inner.js-carousel-inner")
    except NoSuchElementException:
        return

    try:
        scroll_height = driver.execute_script("return arguments[0].scrollHeight;", container)
        viewport_height = driver.execute_script("return arguments[0].clientHeight;", container)
        if not scroll_height or not viewport_height or scroll_height <= viewport_height:
            return

        position = 0
        while position < scroll_height:
            driver.execute_script("arguments[0].scrollTop = arguments[1];", container, position)
            time.sleep(0.5)
            position += viewport_height
        driver.execute_script("arguments[0].scrollTop = 0;", container)
        time.sleep(0.5)
    except Exception as e:
        logging.warning(f"Could not scroll the viewer to preload page images: {e}")


def _count_carousel_items(driver):
    """Returns the number of slide items present in the carousel."""
    try:
        return len(driver.find_elements(By.CSS_SELECTOR, ".carousel-inner.js-carousel-inner .item"))
    except Exception:
        return 0


def _get_active_page_image_element(driver, timeout=30):
    """Waits for the image of the currently active slide to be fully loaded and returns it."""
    selector = ".carousel-inner.js-carousel-inner .item.active img.page-view"

    def _loaded_image(drv):
        elements = drv.find_elements(By.CSS_SELECTOR, selector)
        for element in elements:
            try:
                if not element.is_displayed():
                    continue
                is_loaded = drv.execute_script(
                    "return arguments[0].complete && arguments[0].naturalWidth > 0;", element
                )
                if is_loaded:
                    return element
            except StaleElementReferenceException:
                continue
        return False

    return WebDriverWait(driver, timeout).until(_loaded_image)


def _capture_current_slide(driver, page_number):
    """
    Captures the currently displayed slide.
    The original, full resolution page image is downloaded when possible;
    otherwise the rendered element is screenshotted as a fallback.
    """
    try:
        image_element = _get_active_page_image_element(driver)
    except TimeoutException:
        logging.warning(f"Slide {page_number} image did not load in time.")
        return None

    image_url = image_element.get_attribute('src')
    image = _download_image(driver, image_url)
    if image is not None:
        return image

    try:
        return Image.open(BytesIO(image_element.screenshot_as_png)).convert('RGB')
    except Exception as e:
        logging.warning(f"Could not screenshot slide {page_number}: {e}")
        return None


def _download_image(driver, image_url):
    """Downloads a page image using the browser session cookies. Returns a PIL Image or None."""
    if not image_url:
        return None
    try:
        session = requests.Session()
        for cookie in driver.get_cookies():
            session.cookies.set(cookie['name'], cookie['value'])
        headers = {
            'User-Agent': driver.execute_script("return navigator.userAgent;"),
            'Referer': driver.current_url
        }
        response = session.get(image_url, headers=headers, timeout=60)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert('RGB')
    except Exception as e:
        logging.warning(f"Could not download page image, falling back to screenshot: {e}")
        return None


def _go_to_next_slide(driver, current_page_number):
    """
    Advances the viewer to the next slide and waits until the active slide actually changed.
    Returns True when the navigation succeeded.
    """
    previous_index = _get_active_slide_index(driver)

    # The viewer ignores synthetic JS clicks, so real user interactions are required.
    for attempt, navigate in enumerate((_send_arrow_right, _click_next_button)):
        try:
            navigate(driver)
        except Exception as e:
            logging.warning(f"Navigation attempt {attempt + 1} failed for slide {current_page_number}: {e}")
            continue

        try:
            WebDriverWait(driver, 10).until(
                lambda drv: _get_active_slide_index(drv) not in (previous_index, -1)
            )
            time.sleep(0.5) # Let the new slide settle before capturing it
            return True
        except TimeoutException:
            logging.warning(f"The active slide did not change after slide {current_page_number}.")

    return False


def _send_arrow_right(driver):
    """Sends the right arrow key to the viewer to move to the next slide."""
    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ARROW_RIGHT)


def _click_next_button(driver):
    """Performs a real mouse click on the viewer's next page control."""
    next_button = driver.find_element(By.ID, "nextPageButton")
    ActionChains(driver).move_to_element(next_button).click().perform()


def _get_active_slide_index(driver):
    """Returns the zero-based index of the currently active slide, or -1 if unknown."""
    try:
        return driver.execute_script(
            "var items = document.querySelectorAll('.carousel-inner.js-carousel-inner .item');"
            "for (var i = 0; i < items.length; i++) {"
            "  if (items[i].classList.contains('active')) { return i; }"
            "}"
            "return -1;"
        )
    except Exception:
        return -1


def _get_total_slides_count(driver):
    """Determines the total number of slides from the page indicator."""
    try:
        page_indicator_element = WebDriverWait(driver, 10).until(
            expected_conditions.visibility_of_element_located((By.CLASS_NAME, "toolbar-page-indicator"))
        )
        numbers = re.findall(r'\d+', page_indicator_element.text)
        if numbers:
            total_slides = int(numbers[-1])
            logging.info(f"Detected a total of {total_slides} slides.")
            return total_slides
    except (TimeoutException, IndexError):
        logging.warning("Could not determine total number of slides.")
    return 0


def _compile_pdf(slides, output_pdf_path):
    """Compiles a list of PIL Image objects into a single PDF file."""
    if not slides:
        logging.warning("No slides were captured, so no PDF will be created.")
        return

    logging.info(f"\nCompiling {len(slides)} slides into a PDF...")
    slides[0].save(
        output_pdf_path, "PDF", save_all=True, append_images=slides[1:]
    )
    logging.info(f"Successfully created PDF: {os.path.basename(output_pdf_path)}")