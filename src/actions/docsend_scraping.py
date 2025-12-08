# -*- coding: utf-8 -*-
"""
Action: docsend_scraping

This action automates the process of downloading a presentation from a DocSend link.
It handles the email authentication, captures each slide, and compiles them into a single PDF.
"""

import os
import time
import re
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from PIL import Image
from io import BytesIO

def run(params, job_context):
    """
    Main entry point for the docsend_scraping action.
    """
    url = params.get('url')
    user_email = params.get('user_email')
    document_name = params.get('document_name', 'scraped_document')

    if not all([url, user_email]):
        return {"status": "error", "message": "Missing required parameters: url or user_email."}

    output_dir = job_context.get('job_output_dir', os.getcwd())
    os.makedirs(output_dir, exist_ok=True)
    
    output_pdf_path = os.path.join(output_dir, f"{document_name}.pdf")

    driver = None
    try:
        driver = _setup_driver()
        
        _navigate_and_authenticate(driver, url, user_email)
        
        _wait_for_viewer_and_dismiss_cookie(driver)
        
        captured_slides = _capture_all_slides(driver)
        
        if captured_slides:
            _compile_pdf(captured_slides, output_pdf_path)
            return {"status": "complete", "message": f"Successfully created PDF: {output_pdf_path}"}
        else:
            return {"status": "error", "message": "No slides were captured."}

    except Exception as e:
        print(f"An error occurred during DocSend scraping: {e}")
        if driver and output_dir:
            error_screenshot_path = os.path.join(output_dir, 'error_screenshot.png')
            driver.save_screenshot(error_screenshot_path)
            print(f"Saved error screenshot to {error_screenshot_path}")
        return {"status": "error", "message": str(e)}

    finally:
        if driver:
            driver.quit()
            print("\nWebDriver closed.")

def _setup_driver():
    """Sets up the Selenium WebDriver."""
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    print("Initializing WebDriver...")
    return webdriver.Chrome(options=options)

def _navigate_and_authenticate(driver, url, email_address):
    """Navigates to the URL and handles the email submission form."""
    print(f"Navigating to: {url}")
    driver.get(url)
    try:
        email_input = WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.ID, "link_auth_form_email"))
        )
        print(f"Entering email address: {email_address}")
        email_input.send_keys(email_address)
        driver.find_element(By.CLASS_NAME, "js-auth-form_submit-button").click()
        print("Submitted email. Waiting for presentation viewer...")
    except TimeoutException:
        print("Email submission form not found. Assuming public access.")

def _wait_for_viewer_and_dismiss_cookie(driver):
    """Waits for the presentation viewer and handles the cookie banner."""
    next_button_selector = (By.ID, "nextPageButton")
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located(next_button_selector))
        print("Presentation viewer loaded.")

        print("Looking for the cookie banner iframe...")
        cookie_iframe = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='ccpa_iframe']"))
        )
        driver.switch_to.frame(cookie_iframe)
        print("Switched to iframe. Clicking 'Accept All'...")

        robust_button_xpath = "//button[contains(., 'Accept All') or contains(., 'Tout accepter')]"
        accept_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, robust_button_xpath))
        )
        accept_button.click()
        print("Cookie banner dismissed.")

    except TimeoutException:
        print("Could not find or interact with the cookie banner. Continuing anyway.")
    finally:
        driver.switch_to.default_content()
        print("Switched focus back to the main page.")
        time.sleep(1)

def _capture_all_slides(driver):
    """Browses through the presentation and captures each slide."""
    captured_slides = []
    total_slides = _get_total_slides(driver)
    
    print("\nStarting slide capture...")
    current_slide_num = 0
    while True:
        try:
            next_button_selector = (By.ID, "nextPageButton")
            next_button_element = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(next_button_selector)
            )

            current_page_element = driver.find_element(By.ID, "page-number")
            current_slide_num = int(current_page_element.text)

            time.sleep(1.5)

            active_content_selector = (By.CSS_SELECTOR, ".item.active .viewer_content-container")
            content_element = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located(active_content_selector)
            )

            png_data = content_element.screenshot_as_png
            slide_image = Image.open(BytesIO(png_data))
            captured_slides.append(slide_image.convert('RGB'))
            print(f"Captured slide {current_slide_num}/{total_slides if total_slides > 0 else '?'}")

            if total_slides > 0 and current_slide_num >= total_slides:
                print("Reached the last slide. Finishing capture.")
                break

            next_button_element.click()

        except (NoSuchElementException, TimeoutException):
            print(f"End of presentation detected after slide {current_slide_num}.")
            break
        except Exception as e:
            print(f"An unexpected error occurred during slide navigation: {e}")
            raise  # Re-raise the exception to be caught by the main run function

    return captured_slides

def _get_total_slides(driver):
    """Determines the total number of slides from the page indicator."""
    try:
        page_indicator_element = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CLASS_NAME, "toolbar-page-indicator"))
        )
        numbers = re.findall(r'\d+', page_indicator_element.text)
        if numbers:
            total_slides = int(numbers[-1])
            print(f"Detected a total of {total_slides} slides.")
            return total_slides
    except (TimeoutException, IndexError):
        print("Could not determine total number of slides.")
    return 0

def _compile_pdf(slides, output_pdf_path):
    """Compiles a list of PIL Image objects into a single PDF file."""
    if not slides:
        print("No slides were captured, so no PDF will be created.")
        return

    print(f"\nCompiling {len(slides)} slides into a PDF...")
    slides[0].save(
        output_pdf_path, "PDF", save_all=True, append_images=slides[1:]
    )
    print(f"Successfully created PDF: {os.path.basename(output_pdf_path)}")
