# -*- coding: utf-8 -*-
"""
Action: papermark_scraping

This action automates the process of downloading a document from a Papermark link
(https://www.papermark.com/view/...).
It handles the email (and optional passcode) authentication, captures every page of
the document and compiles them into a single PDF.

The heavy lifting that is identical to DocSend (WebDriver setup, image download,
blank page detection and PDF compilation) is reused from the `docsend_scraping`
action; only the viewer specific navigation logic is implemented here.
"""

import os
import time
import re
import base64
import shutil
import logging
from io import BytesIO

from PIL import Image

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from src.actions.docsend_scraping import (
    _setup_driver,
    _download_image,
    _is_blank_image,
    _to_rgb_on_white,
    _compile_pdf,
)

PAGE_IMAGE_SELECTOR = "img.viewer-image-mobile, img.viewer-image-desktop"


def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Main entry point for the papermark_scraping action.
    """
    url = params.get('url')
    user_email = params.get('user_email')
    passcode = params.get('passcode')
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

        _navigate_and_authenticate(driver, url, user_email, passcode)
        _wait_for_viewer(driver)

        total_pages = _get_total_pages_count(driver)
        logging.info(f"Detected {total_pages} pages in the Papermark viewer.")

        captured_pages = _capture_all_pages(driver, total_pages)

        if captured_pages:
            _compile_pdf(captured_pages, output_pdf_path)
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
            result = {"job_id": job_id, "status": "failed", "error": "No pages were captured."}

    except Exception as e:
        logging.error(f"An error occurred during Papermark scraping: {e}")
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


def _navigate_and_authenticate(driver, url, email_address, passcode=None):
    """Navigates to the URL and handles the email / passcode form of the Papermark gate."""
    logging.info(f"Navigating to: {url}")
    driver.get(url)

    submitted = False
    try:
        email_input = WebDriverWait(driver, 20).until(
            expected_conditions.visibility_of_element_located((By.ID, "email"))
        )
        logging.info(f"Entering email address: {email_address}")
        email_input.send_keys(email_address)
        submitted = True
    except TimeoutException:
        logging.info("Email form not found. Assuming the document is publicly accessible.")

    if passcode:
        try:
            passcode_input = driver.find_element(By.CSS_SELECTOR, "input#password, input[name='password']")
            logging.info("Entering passcode.")
            passcode_input.send_keys(passcode)
            submitted = True
        except Exception:
            logging.info("No passcode field found on the page.")

    if submitted:
        _submit_access_form(driver)


def _submit_access_form(driver):
    """Clicks the 'Continue' button of the access form, falling back to a JS click."""
    button_xpath = ("//button[@type='submit' or contains(., 'Continue') or contains(., 'CONTINUE')"
                    " or contains(., 'Continuer')]")
    submit_button = WebDriverWait(driver, 15).until(
        expected_conditions.element_to_be_clickable((By.XPATH, button_xpath))
    )
    try:
        submit_button.click()
    except ElementClickInterceptedException:
        logging.warning("Direct click on the access form button failed, retrying with a JS click.")
        driver.execute_script("arguments[0].click();", submit_button)
    logging.info("Submitted the access form. Waiting for the document viewer...")


def _wait_for_viewer(driver):
    """Waits for the Papermark viewer and its first page image to be available."""
    try:
        WebDriverWait(driver, 60).until(
            lambda drv: _count_page_image_elements(drv) > 0
        )
        logging.info("Papermark viewer loaded.")
    except TimeoutException as e:
        logging.error("Papermark viewer did not load in time.")
        raise e


def _count_page_image_elements(driver):
    """Returns the number of page image elements present in the viewer."""
    try:
        return driver.execute_script(
            "return document.querySelectorAll(arguments[0]).length;", PAGE_IMAGE_SELECTOR
        ) or 0
    except Exception:
        return 0


def _get_total_pages_count(driver):
    """
    Determines the total number of pages.
    The viewer renders one image element per page, and also displays a `current / total`
    indicator which is used as a cross-check.
    """
    element_count = _count_page_image_elements(driver)
    indicator_total = _get_indicator_total(driver)
    total = max(element_count, indicator_total)
    if not total:
        total = 1
    return total


def _get_indicator_total(driver):
    """Reads the total number of pages from the `current / total` toolbar indicator."""
    try:
        text = driver.execute_script("return document.body.innerText || '';")
        match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if match:
            return int(match.group(2))
    except Exception:
        pass
    return 0


def _capture_all_pages(driver, total_pages):
    """
    Captures every page of the document.
    Page images are lazily loaded by the viewer, so pages that are not loaded yet are
    reached by navigating forward before being downloaded.
    Returns a list of PIL Images.
    """
    logging.info(f"\nStarting capture of {total_pages} pages...")
    pages = []

    for page_number in range(1, total_pages + 1):
        image = _capture_page(driver, page_number, total_pages)
        if image is not None:
            pages.append(image)
            logging.info(f"Captured page {page_number}/{total_pages}.")
        else:
            logging.warning(f"Could not capture page {page_number}/{total_pages}.")

    logging.info(f"Finished capturing pages. Total: {len(pages)}")
    return pages


def _capture_page(driver, page_number, total_pages):
    """Downloads the image of the given page (1-based), navigating to it when required."""
    for attempt in range(3):
        image_url = _wait_for_page_image_url(driver, page_number - 1, timeout=15)
        if not image_url:
            logging.info(f"Page {page_number} is not loaded yet. Navigating to it.")
            _go_to_page(driver, page_number, total_pages)
            image_url = _wait_for_page_image_url(driver, page_number - 1, timeout=45)
        if not image_url:
            continue

        image = _download_image(driver, image_url)
        if image is None:
            continue
        if _is_blank_image(image):
            logging.warning(f"Page image {page_number} looks blank (attempt {attempt + 1}). Retrying.")
            time.sleep(1)
            continue
        return image

    return _screenshot_page(driver, page_number)


def _wait_for_page_image_url(driver, index, timeout=30):
    """
    Waits until the page element at `index` exposes a real, fully loaded image source.
    Placeholder images (`blank.gif`, data URLs) are ignored. Returns the URL or None.
    """
    def _loaded_url(drv):
        return drv.execute_script(
            "var imgs = document.querySelectorAll(arguments[0]);"
            "var img = imgs[arguments[1]];"
            "if (!img) { return null; }"
            "if (!img.complete || img.naturalWidth <= 1) { return null; }"
            "var src = img.currentSrc || img.src || img.getAttribute('data-src');"
            "if (!src || src.indexOf('data:') === 0 || src.indexOf('blank.gif') !== -1) { return null; }"
            "return src;",
            PAGE_IMAGE_SELECTOR,
            index
        ) or False

    try:
        return WebDriverWait(driver, timeout, poll_frequency=0.5).until(_loaded_url)
    except Exception:
        return None


def _go_to_page(driver, page_number, total_pages):
    """
    Navigates the viewer forward until the requested page (1-based) is displayed.
    The viewer only reacts to real user interactions, hence the arrow key / mouse click.
    """
    for _ in range(total_pages + 1):
        current_page = _get_current_page_number(driver)
        if current_page >= page_number:
            break
        if not _go_to_next_page(driver):
            break
    time.sleep(1)


def _go_to_next_page(driver):
    """Advances the viewer by one page. Returns True when the current page actually changed."""
    previous_page = _get_current_page_number(driver)

    for navigate in (_send_arrow_right, _click_next_button):
        try:
            navigate(driver)
        except Exception as e:
            logging.warning(f"Page navigation attempt failed: {e}")
            continue

        try:
            WebDriverWait(driver, 10).until(
                lambda drv: _get_current_page_number(drv) > previous_page
            )
            time.sleep(0.5)
            return True
        except TimeoutException:
            logging.warning(f"The viewer did not move past page {previous_page}.")

    return False


def _send_arrow_right(driver):
    """Sends the right arrow key to the viewer to move to the next page."""
    ActionChains(driver).send_keys(Keys.ARROW_RIGHT).perform()


def _click_next_button(driver):
    """Performs a real mouse click on the viewer's next page control."""
    next_button = driver.find_element(
        By.CSS_SELECTOR, "button[aria-label*='next' i], button#nextPageButton"
    )
    ActionChains(driver).move_to_element(next_button).click().perform()


def _get_current_page_number(driver):
    """Returns the page number currently displayed by the viewer, or 0 when unknown."""
    try:
        text = driver.execute_script("return document.body.innerText || '';")
        match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 0


def _screenshot_page(driver, page_number):
    """Fallback capture: screenshots the rendered page element."""
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, PAGE_IMAGE_SELECTOR)
        element = elements[page_number - 1]
        return _to_rgb_on_white(Image.open(BytesIO(element.screenshot_as_png)))
    except Exception as e:
        logging.warning(f"Could not screenshot page {page_number}: {e}")
        return None
