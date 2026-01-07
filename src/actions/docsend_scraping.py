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
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
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

        _wait_for_viewer(driver)

        captured_slides = _capture_all_slides(driver)

        if captured_slides:
            _compile_pdf(captured_slides, output_pdf_path)
            with open(output_pdf_path, "rb") as pdf_file:
                encoded_string = base64.b64encode(pdf_file.read()).decode('utf-8')
            result = {
                "job_id": job_id,
                "status": "complete",
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
    options = Options()
    if os.environ.get('HEADLESS_BROWSER', 'true').lower() == 'true':
        options.add_argument('--headless')
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
    _handle_overlays(driver)

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
    next_button_selector = (By.ID, "nextPageButton")
    try:
        WebDriverWait(driver, 20).until(expected_conditions.presence_of_element_located(next_button_selector))
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
    """Browses through the presentation and captures each slide."""
    captured_slides = []
    total_slides = _get_total_slides(driver)

    logging.info("\nStarting slide capture...")
    current_slide_num = 0
    while True:
        try:
            _handle_overlays(driver)

            next_button_selector = (By.ID, "nextPageButton")
            next_button_element = WebDriverWait(driver, 10).until(
                expected_conditions.element_to_be_clickable(next_button_selector)
            )

            current_page_element = driver.find_element(By.ID, "page-number")
            current_slide_num = int(current_page_element.text)
            time.sleep(1)

            active_content_selector = (By.CSS_SELECTOR, ".item.active .viewer_content-container")
            content_element = WebDriverWait(driver, 10).until(
                expected_conditions.visibility_of_element_located(active_content_selector)
            )

            png_data = content_element.screenshot_as_png
            slide_image = Image.open(BytesIO(png_data))
            captured_slides.append(slide_image.convert('RGB'))
            logging.info(f"Captured slide {current_slide_num}/{total_slides if total_slides > 0 else '?'}")

            if total_slides and current_slide_num >= total_slides:
                logging.info("Reached the last slide. Finishing capture.")
                break

            next_button_element.click()

        except (NoSuchElementException, TimeoutException):
            logging.info(f"End of presentation detected after slide {current_slide_num}.")
            break
        except Exception as e:
            logging.error(f"An unexpected error occurred during slide navigation: {e}")
            raise

    return captured_slides


def _get_total_slides(driver):
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
