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
    headless = params.get('headless', True)

    if not all([url, username, password]):
        return {"status": "error", "message": "Missing required parameters: url, username, or password."}

    # Use a hardcoded root path to avoid long path issues on Windows
    download_root = 'C:/temp/drooms_scraping'
        
    os.makedirs(download_root, exist_ok=True)
    print(f"Using download root: {download_root}")

    driver = None
    try:
        driver = _setup_driver(headless=headless)
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
            output_dir = job_context.get('job_output_dir')
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

def _setup_driver(headless=True):
    """Sets up the Selenium WebDriver."""
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
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

def _expand_all_folders(driver):
    """Iteratively expands all folders on the page until none are left collapsed."""
    print("Expanding all folders...")
    attempts = 0
    max_attempts = 1000  # Safety break to prevent infinite loops

    while attempts < max_attempts:
        attempts += 1
        print(f"--- Expansion pass {attempts} ---")
        
        try:
            # Find all collapsed folders that are visible
            collapsed_folders = driver.find_elements(By.CSS_SELECTOR, "app-index-list-point.folder:not(.expanded)")
            
            if not collapsed_folders:
                print("--- No more collapsed folders found. Expansion complete. ---")
                break

            print(f"Found {len(collapsed_folders)} collapsed folders to expand in this pass.")
            
            # Click the first visible collapsed folder
            folder_to_expand = collapsed_folders[0]
            arrow_icon = folder_to_expand.find_element(By.CSS_SELECTOR, "div[data-e2e='index-arrow-icon']")
            
            # Scroll to the folder and click
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", arrow_icon)
            time.sleep(0.5)
            arrow_icon.click()
            
            folder_name_element = folder_to_expand.find_element(By.CSS_SELECTOR, ".index-description-text")
            print(f"Expanded: {folder_name_element.text.strip().replace(chr(10), ' ')}")
            
            # Wait for the UI to update
            time.sleep(1.5)

        except (StaleElementReferenceException, ElementNotInteractableException):
            print("Stale element or not interactable, retrying pass.")
            time.sleep(1)
            continue
        except Exception as e:
            print(f"An unexpected error occurred during folder expansion: {e}")
            break
            
    if attempts >= max_attempts:
        print("Warning: Reached max expansion attempts. The folder tree may be incomplete.")
        
    print("Finished expanding folders.")

def _gather_all_items(driver):
    """Gathers all items by scrolling through the virtual list."""
    print("Gathering all items...")
    
    # Scroll to top before starting
    _scroll_to_top(driver)

    all_items_map = {}
    last_count = -1
    consecutive_no_change = 0

    while consecutive_no_change < 3: # Stop after 3 scrolls with no new items
        nodes = driver.find_elements(By.CSS_SELECTOR, "app-index-list-point")
        
        for node in nodes:
            try:
                data_e2e = node.get_attribute('data-e2e')
                if not data_e2e or 'inbox' in data_e2e or 'trash' in data_e2e:
                    continue

                if data_e2e in all_items_map:
                    continue

                order_text = ""
                try:
                    order_element = node.find_element(By.CSS_SELECTOR, ".index-description-order")
                    order_text = order_element.text.strip()
                except NoSuchElementException:
                    continue
                
                if not order_text:
                    continue

                node_text_element = node.find_element(By.CSS_SELECTOR, ".index-description-text")
                base_name = node_text_element.text.strip()
                if not base_name:
                    continue

                # Do not include the order prefix in the item's text to keep paths short.
                sanitized_name = _sanitize_filename(base_name)
                is_folder = 'folder' in node.get_attribute('class')
                
                all_items_map[data_e2e] = {
                    "id": data_e2e,
                    "order": order_text,
                    "text": sanitized_name,
                    "is_folder": is_folder,
                }
            except (NoSuchElementException, StaleElementReferenceException):
                continue
        
        current_count = len(all_items_map)
        if current_count == last_count:
            consecutive_no_change += 1
        else:
            consecutive_no_change = 0
        last_count = current_count

        # Scroll down
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.PAGE_DOWN)
        time.sleep(1)

    all_items = list(all_items_map.values())
    print(f"Gathered {len(all_items)} unique items.")
    return all_items

def _scroll_to_top(driver):
    """Scrolls the virtual scroll viewport to the top."""
    print("Scrolling virtual list to the top...")
    try:
        scroll_viewport = driver.find_element(By.CSS_SELECTOR, "cdk-virtual-scroll-viewport")
        driver.execute_script("arguments[0].scrollTop = 0;", scroll_viewport)
        print("Virtual list scrolled to top.")
    except NoSuchElementException:
        print("Warning: cdk-virtual-scroll-viewport not found. Falling back to window scroll.")
        driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(2)

def _process_all_items(driver, items, download_root):
    """
    Iteratively processes all items to create folders and download documents.
    """
    # Ensure we start from a known state
    _scroll_to_top(driver)

    path_map = {"": download_root}

    # Create all folder structures first
    sorted_folders = sorted([item for item in items if item['is_folder']], key=lambda x: tuple(map(int, x['order'].split('.'))))
    for item in sorted_folders:
        order_parts = item['order'].split('.')
        parent_order = ".".join(order_parts[:-1])
        
        parent_path = path_map.get(parent_order, download_root)
        # item['text'] is now the clean, sanitized name without prefix.
        new_path = os.path.join(parent_path, item['text'])
        os.makedirs(new_path, exist_ok=True)
        path_map[item['order']] = new_path

    # Process documents
    sorted_docs = sorted([item for item in items if not item['is_folder']], key=lambda x: tuple(map(int, x['order'].split('.'))))
    for item in sorted_docs:
        order_parts = item['order'].split('.')
        parent_order = ".".join(order_parts[:-1])
        
        parent_path = path_map.get(parent_order, download_root)
        # item['text'] is the clean name.
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
            time.sleep(0.5)
            element_to_click.click()
            _process_document(driver, pdf_path)
            WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "app-index-list-view")))
        except Exception as e:
            print(f"    Could not process document '{item['text']}'. Error: {e}")
            driver.get(driver.current_url) 
            WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "app-index-list-view")))

def _process_document(driver, pdf_path):
    """Screenshots and assembles a document into a single PDF."""
    print(f"    -> Saving to: {os.path.basename(pdf_path)}")
    temp_img_dir = os.path.join(os.path.dirname(pdf_path), "temp_images_" + os.path.basename(pdf_path))
    os.makedirs(temp_img_dir, exist_ok=True)
    
    image_files = []
    body = driver.find_element(By.TAG_NAME, 'body')

    try:
        driver.execute_script("document.documentElement.requestFullscreen();")
        time.sleep(2)

        viewer = WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='doc-reader-document-component']")))
        time.sleep(2)

        processed_pages = set()
        no_new_pages_count = 0

        while True:
            initial_page_count = len(processed_pages)
            
            page_wrappers = viewer.find_elements(By.CSS_SELECTOR, ".page-wrapper")
            for page_wrapper in page_wrappers:
                try:
                    page_id = page_wrapper.get_attribute('data-e2e')
                    if page_id and page_id not in processed_pages:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_wrapper)
                        time.sleep(0.5)

                        img_path = os.path.join(temp_img_dir, f"{page_id}.png")
                        page_wrapper.screenshot(img_path)
                        image_files.append((page_id, img_path))
                        processed_pages.add(page_id)
                except StaleElementReferenceException:
                    continue
            
            body.send_keys(Keys.PAGE_DOWN)
            time.sleep(1)

            if len(processed_pages) == initial_page_count:
                no_new_pages_count += 1
            else:
                no_new_pages_count = 0

            if no_new_pages_count >= 3:
                break

            if len(processed_pages) > 300:
                break

        if image_files:
            image_files.sort(key=lambda x: int(re.search(r'\d+$', x[0]).group()))
            sorted_image_paths = [p[1] for p in image_files]
            
            if sorted_image_paths:
                first_image = Image.open(sorted_image_paths[0]).convert('RGB')
                other_images = [Image.open(p).convert('RGB') for p in sorted_image_paths[1:]]
                first_image.save(pdf_path, save_all=True, append_images=other_images)

    finally:
        driver.execute_script("document.exitFullscreen();")
        time.sleep(1)
        shutil.rmtree(temp_img_dir, ignore_errors=True)
        try:
            close_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-e2e='close'], [aria-label='Close']")))
            close_button.click()
        except TimeoutException:
            driver.back()
