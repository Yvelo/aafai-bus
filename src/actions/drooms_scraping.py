# -*- coding: utf-8 -*-
"""
Action: drooms_scraping

This action automates the process of downloading documents from a D-Rooms virtual data room.
It is designed to handle the complexities of a modern, JavaScript-heavy web application.

**Disclaimer:** This script is for educational and archival purposes only. Ensure you have
the legal right and explicit permission from the data room owner before scraping any content.
Unauthorized scraping may violate the terms of service of the platform.
"""

import os
import time
import shutil
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException, ElementNotInteractableException

from PIL import Image

# --- Main Action Function ---

def run(params, job_context):
    """
    Main entry point for the drooms_scraping action.
    """
    url = params.get('url')
    username = params.get('username')
    password = params.get('password')

    if not all([url, username, password]):
        return {"status": "error", "message": "Missing required parameters: url, username, or password."}

    output_dir = job_context.get('job_output_dir')
    # Persistent download root, placed alongside the job-specific output directory
    if output_dir:
        download_root = os.path.join(os.path.dirname(output_dir), 'drooms_download')
    else:
        # Fallback to a directory in the current working directory if job_output_dir is not set
        download_root = os.path.join(os.getcwd(), 'drooms_download')
        
    os.makedirs(download_root, exist_ok=True)
    print(f"Using download root: {download_root}")

    driver = None
    try:
        driver = _setup_driver()
        _login(driver, url, username, password)
        
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "app-index-list-point")))
        print("Successfully logged in and index is visible.")

        _expand_all_folders(driver)
        all_items = _gather_all_items(driver)
        _process_all_items(driver, all_items, download_root)

        return {"status": "complete", "message": f"D-Rooms scraping completed. Files saved to {download_root}"}

    except Exception as e:
        print(f"An error occurred during D-Rooms scraping: {e}")
        if driver:
            # Ensure output_dir exists for error screenshot
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                error_screenshot_path = os.path.join(output_dir, 'error_screenshot.png')
                driver.save_screenshot(error_screenshot_path)
                print(f"Saved error screenshot to {error_screenshot_path}")
        return {"status": "error", "message": str(e)}

    finally:
        if driver:
            driver.quit()


# --- Helper Functions ---

def _setup_driver():
    """Sets up the Selenium WebDriver."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1600") # Increased height for better rendering
    
    print("Initializing WebDriver...")
    return webdriver.Chrome(options=options)

def _login(driver, url, username, password):
    """Handles the D-Rooms login process."""
    print(f"Navigating to login page: {url}")
    driver.get(url)
    wait = WebDriverWait(driver, 30)
    
    try:
        print("Login Step 1: Entering email.")
        try:
            cookie_button = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll")))
            cookie_button.click()
            print("Accepted cookies.")
        except TimeoutException:
            print("No cookie consent button found.")

        user_field = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[data-e2e='email-input']")))
        user_field.send_keys(username)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-e2e='check-email-button']"))).click()
        print("Email submitted.")

        print("Login Step 2: Entering password.")
        pass_field = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[data-e2e='password-input']")))
        pass_field.send_keys(password)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-e2e='submit-credentials-button']"))).click()
        print("Password submitted.")

    except TimeoutException as e:
        raise Exception(f"Login failed. Element not found: {e}")

def _sanitize_filename(name):
    """Creates a valid filename from a string, handling newlines."""
    name_no_newlines = name.replace('\n', ' ')
    return re.sub(r'[<>:"/\\|?*]', '_', name_no_newlines).strip()

def _get_indent_level(node):
    """Determines the indentation level of a node from its CSS padding."""
    try:
        icon_container = node.find_element(By.CSS_SELECTOR, ".index-icons")
        padding_str = icon_container.value_of_css_property("padding-left")
        return int(re.search(r'\d+', padding_str).group())
    except (NoSuchElementException, AttributeError):
        return 0

def _expand_all_folders(driver):
    """Iteratively expands all folders on the page, with detailed logging."""
    print("Expanding all folders...")
    for i in range(10):
        print(f"--- Expansion pass {i + 1} ---")
        newly_expanded_in_pass = False
        try:
            all_folders = driver.find_elements(By.CSS_SELECTOR, "app-index-list-point.folder")
            if not all_folders:
                print("No folders found on the page.")
                break

            print(f"Found {len(all_folders)} total folders. Current state:")
            for folder in all_folders:
                try:
                    is_expanded = 'expanded' in folder.get_attribute('class')
                    folder_text_element = folder.find_element(By.CSS_SELECTOR, ".index-description-text")
                    folder_name = folder_text_element.text.strip().replace('\n', ' ')
                    status = "Expanded" if is_expanded else "Collapsed"
                    indent = _get_indent_level(folder)
                    indent_prefix = "  " * (indent // 20)  # Assuming ~20px indent per level
                    print(f"{indent_prefix}- {folder_name} [{status}]")
                except StaleElementReferenceException:
                    continue

            # Find the next collapsed folder and expand it
            for folder in all_folders:
                try:
                    is_expanded = 'expanded' in folder.get_attribute('class')
                    if not is_expanded:
                        arrow_icon = folder.find_element(By.CSS_SELECTOR, "div[data-e2e='index-arrow-icon']")
                        
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", arrow_icon)
                        time.sleep(0.5)
                        arrow_icon.click()
                        time.sleep(1.5)
                        
                        newly_expanded_in_pass = True
                except (StaleElementReferenceException, ElementNotInteractableException):
                    print("Stale element encountered, starting a new expansion pass.")
                    newly_expanded_in_pass = True
                    break
            
            if not newly_expanded_in_pass:
                print("--- No more folders to expand. Expansion complete. ---")
                break
        
        except Exception as e:
            print(f"An unexpected error occurred during folder expansion: {e}")
            break
            
    print("Finished expanding folders.")


def _gather_all_items(driver):
    """Gathers information about all items after expansion, including order index."""
    print("Gathering all items...")
    all_items = []
    nodes = driver.find_elements(By.CSS_SELECTOR, "app-index-list-point")
    for i, node in enumerate(nodes):
        try:
            data_e2e = node.get_attribute('data-e2e')
            if not data_e2e or 'inbox' in data_e2e or 'trash' in data_e2e:
                continue

            # Extract the order index text
            order_text = ""
            try:
                order_element = node.find_element(By.CSS_SELECTOR, ".index-description-order")
                order_text = order_element.text.strip()
            except NoSuchElementException:
                pass # Not all items have an order index

            node_text_element = node.find_element(By.CSS_SELECTOR, ".index-description-text")
            base_name = node_text_element.text.strip()
            if not base_name:
                continue

            # Combine order index and name
            full_name = f"{order_text} {base_name}".strip()
            sanitized_name = _sanitize_filename(full_name)

            is_folder = "folder" in node.find_element(By.CSS_SELECTOR, "drs-index-avatar use").get_attribute("xlink:href")
            indent_level = _get_indent_level(node)
            
            all_items.append({
                "index": i,
                "id": data_e2e,
                "text": sanitized_name,
                "is_folder": is_folder,
                "indent": indent_level,
            })
        except (NoSuchElementException, StaleElementReferenceException):
            continue
    print(f"Gathered {len(all_items)} items.")
    return all_items

def _process_all_items(driver, items, download_root):
    """
    Iteratively processes all items to create folders and download documents.
    """
    path_stack = [(download_root, -1)]  # Stack of (path, indent_level)

    for item in items:
        current_indent = item['indent']

        while path_stack and current_indent <= path_stack[-1][1]:
            path_stack.pop()
        
        parent_path = path_stack[-1][0]

        if item['is_folder']:
            new_path = os.path.join(parent_path, item['text'])
            print(f"Ensuring folder exists: {new_path}")
            os.makedirs(new_path, exist_ok=True)
            path_stack.append((new_path, current_indent))
        else:
            pdf_path = os.path.join(parent_path, f"{item['text']}.pdf")
            if os.path.exists(pdf_path):
                print(f"  Skipping existing document: {item['text']}")
                continue
            
            print(f"  Processing document: {item['text']}")
            try:
                element_to_click = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, f"app-index-list-point[data-e2e='{item['id']}'] .index-description-text"))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element_to_click)
                time.sleep(0.2)
                element_to_click.click()
                _process_document(driver, pdf_path)
                WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "app-index-list-view")))
            except Exception as e:
                print(f"    Could not process document '{item['text']}'. Error: {e}")
                driver.get(driver.current_url) 
                WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "app-index-list-view")))


def _process_document(driver, pdf_path):
    """Screenshots and assembles a document into a single PDF using robust capture methods."""
    print(f"    -> Saving to: {os.path.basename(pdf_path)}")
    temp_img_dir = os.path.join(os.path.dirname(pdf_path), "temp_images_" + os.path.basename(pdf_path))
    os.makedirs(temp_img_dir, exist_ok=True)
    
    image_files = []
    body = driver.find_element(By.TAG_NAME, 'body')

    try:
        body.send_keys(Keys.F11)
        print("    -> Entered fullscreen mode.")
        time.sleep(2)

        viewer = WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='doc-reader-document-component']")))
        print("    -> Viewer loaded.")
        time.sleep(2)

        is_landscape = False
        try:
            first_page = viewer.find_element(By.CSS_SELECTOR, ".page-wrapper")
            page_size = first_page.size
            if page_size['width'] > page_size['height']:
                is_landscape = True
            print(f"    -> Document is {'landscape' if is_landscape else 'portrait'}.")
        except NoSuchElementException:
            print("    -> Could not determine page orientation, defaulting to portrait.")

        scrolls_per_page = 14 if is_landscape else 21
        
        processed_pages = set()
        no_new_pages_count = 0

        while True:
            initial_page_count = len(processed_pages)
            
            page_wrappers = viewer.find_elements(By.CSS_SELECTOR, ".page-wrapper")
            for page_wrapper in page_wrappers:
                try:
                    page_id = page_wrapper.get_attribute('data-e2e')
                    if page_id and page_id not in processed_pages:
                        # Scroll each page into view before taking a screenshot
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_wrapper)
                        time.sleep(0.5) # Allow time for rendering after scroll

                        img_path = os.path.join(temp_img_dir, f"{page_id}.png")
                        page_wrapper.screenshot(img_path)
                        image_files.append((page_id, img_path))
                        processed_pages.add(page_id)
                        print(f"    -> Captured page {page_id}")
                except StaleElementReferenceException:
                    continue
            
            print(f"    -> Scrolling down ({scrolls_per_page} key presses)...")
            for _ in range(scrolls_per_page):
                body.send_keys(Keys.ARROW_DOWN)
                time.sleep(0.05)
            time.sleep(1)

            if len(processed_pages) == initial_page_count:
                no_new_pages_count += 1
                print("    -> No new pages found in this scroll cycle.")
            else:
                no_new_pages_count = 0

            if no_new_pages_count >= 2:
                print("    -> Reached end of document.")
                break

            if len(processed_pages) > 250:  # Increased safety break
                print("    -> Safety break: captured 250 pages.")
                break

        if image_files:
            image_files.sort(key=lambda x: int(re.search(r'\d+$', x[0]).group()))
            sorted_image_paths = [p[1] for p in image_files]
            
            if sorted_image_paths:
                print(f"    -> Creating PDF with {len(sorted_image_paths)} pages...")
                try:
                    first_image = Image.open(sorted_image_paths[0]).convert('RGB')
                    other_images = [Image.open(p).convert('RGB') for p in sorted_image_paths[1:]]
                    first_image.save(pdf_path, save_all=True, append_images=other_images)
                    print(f"    -> Successfully created PDF: {os.path.basename(pdf_path)}")
                except Exception as img_err:
                    print(f"    -> Error creating PDF: {img_err}")

    finally:
        body.send_keys(Keys.F11)
        print("    -> Exited fullscreen mode.")
        time.sleep(1)

        if os.path.exists(temp_img_dir):
            shutil.rmtree(temp_img_dir)
        try:
            close_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-e2e='close'], [aria-label='Close']")))
            close_button.click()
            print("    -> Closed document viewer.")
        except TimeoutException:
            print("    -> Could not find close button; navigating back to recover.")
            driver.back()
