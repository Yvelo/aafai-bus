import time
import os
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from PIL import Image
from io import BytesIO


def browse_docsend_presentation(url, email_address, output_pdf_name="presentation.pdf"):
    """
    Handles authentication, dismisses the cookie banner, captures all slides,
    and compiles them into a single PDF file.
    """
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")
    options.add_experimental_option('excludeSwitches', ['enable-automation'])

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"Error initializing WebDriver: {e}")
        return

    captured_slides = []  # List to hold image objects in memory

    try:
        print(f"Navigating to: {url}")
        driver.get(url)

        # --- STEP 1: Handle Email Submission ---
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

        # --- STEP 2: Wait for Viewer and Dismiss Cookie Banner ---
        next_button_selector = (By.ID, "nextPageButton")
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located(next_button_selector))
            print("Presentation viewer loaded.")

            # Switch to iframe to handle cookie banner
            print("Looking for the cookie banner iframe...")
            cookie_iframe = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='ccpa_iframe']"))
            )
            driver.switch_to.frame(cookie_iframe)
            print("Switched to iframe. Clicking 'Accept All'...")

            # Robust button click
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

        # --- STEP 3: Get Total Number of Slides ---
        total_slides = 0
        try:
            page_indicator_element = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.CLASS_NAME, "toolbar-page-indicator"))
            )
            numbers = re.findall(r'\d+', page_indicator_element.text)
            if numbers:
                total_slides = int(numbers[-1])
                print(f"Detected a total of {total_slides} slides.")
        except (TimeoutException, IndexError):
            print("Could not determine total number of slides.")

        # --- STEP 4: Browse and Capture Slides into Memory ---
        print("\nStarting slide capture...")
        current_slide_num = 0
        while True:
            try:
                next_button_element = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(next_button_selector)
                )

                current_page_element = driver.find_element(By.ID, "page-number")
                current_slide_num = int(current_page_element.text)

                time.sleep(1.5)

                # Find the content element for the active slide
                active_content_selector = (By.CSS_SELECTOR, ".item.active .viewer_content-container")
                content_element = WebDriverWait(driver, 10).until(
                    EC.visibility_of_element_located(active_content_selector)
                )

                # Get screenshot as binary data and convert to a Pillow Image object
                png_data = content_element.screenshot_as_png
                slide_image = Image.open(BytesIO(png_data))

                # Convert to RGB to avoid issues with transparency when saving to PDF
                captured_slides.append(slide_image.convert('RGB'))
                print(f"Captured slide {current_slide_num}/{total_slides} into memory.")

                if total_slides > 0 and current_slide_num >= total_slides:
                    print("Reached the last slide. Finishing capture.")
                    break

                next_button_element.click()

            except (NoSuchElementException, TimeoutException):
                print(f"End of presentation detected after slide {current_slide_num}.")
                break
            except Exception as e:
                print(f"An unexpected error occurred during slide navigation: {e}")
                driver.save_screenshot("error_screenshot.png")
                break

        # --- STEP 5: Compile Images into a Single PDF ---
        if captured_slides:
            print(f"\nCompiling {len(captured_slides)} slides into a PDF...")
            # The first image is the base, the rest are appended
            captured_slides[0].save(
                output_pdf_name, "PDF", save_all=True, append_images=captured_slides[1:]
            )
            print(f"Successfully created PDF: {output_pdf_name}")
        else:
            print("No slides were captured, so no PDF will be created.")

    finally:
        if driver:
            driver.quit()
            print("\nWebDriver closed.")


# --- SCRIPT EXECUTION ---
DOCSEND_URL = os.environ.get('DOCSEND_URL')
USER_EMAIL = os.environ.get('USER_EMAIL')
DOCUMENT_NAME = os.environ.get('DOCUMENT_NAME')
browse_docsend_presentation(DOCSEND_URL, USER_EMAIL, DOCUMENT_NAME)