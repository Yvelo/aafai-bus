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
import re
import shutil
import time
import tempfile
from PIL import Image
from selenium import webdriver
from selenium.common.exceptions import (ElementNotInteractableException,
                                        NoSuchElementException,
                                        StaleElementReferenceException,
                                        TimeoutException)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.driver_cache import DriverCacheManager
from src.browser_config import get_chrome_options

# --- Main Action Function ---

def execute(job_id, params, download_dir, write_result_to_outbound):
    """
    Main entry point for the drooms_scraping action.
    """
    url = params.get('url')
    username = params.get('username')
    password = params.get('password')
    headless = os.environ.get('HEADLESS_BROWSER', 'true').lower() == 'true'
    debug_mode = params.get('debug_mode', False)

    if not all([url, username, password]):
        result = {"status": "error", "message": "Missing required parameters: url, username, or password."}
        write_result_to_outbound(job_id, result)
        return

    download_root = 'C:/temp/drooms_scraping'
    os.makedirs(download_root, exist_ok=True)
    print(f"Using download root: {download_root}")

    # Create a job-specific directory for driver logs and cache
    job_download_dir = os.path.join(download_dir, job_id)
    os.makedirs(job_download_dir, exist_ok=True)

    driver = None
    try:
        driver, service = _setup_driver(job_download_dir)
        _login(driver, url, username, password)
        
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "app-index-list-point")))
        print("Successfully logged in and index is visible.")

        _expand_all_folders(driver, debug_mode=debug_mode)
        all_items = _gather_all_items(driver)
        _process_all_items(driver, all_items, download_root)

        result = {"status": "complete", "message": f"D-Rooms scraping completed. Files saved to {download_root}"}

    except Exception as e:
        print(f"An error occurred during D-Rooms scraping: {e}")
        if driver:
            error_screenshot_path = os.path.join(download_dir, 'error_screenshot.png')
            driver.save_screenshot(error_screenshot_path)
            print(f"Saved error screenshot to {error_screenshot_path}")
        result = {"status": "error", "message": str(e)}

    finally:
        if driver:
            driver.quit()
        if driver and hasattr(driver, 'temp_dir'):
            time.sleep(1) # Give time for processes to release file handles
            try:
                shutil.rmtree(driver.temp_dir)
            except OSError as e:
                print(f"Warning: Could not remove temporary directory {driver.temp_dir}: {e}")
        write_result_to_outbound(job_id, result)


# --- Helper Functions ---

def _setup_driver(download_dir):
    """Sets up the Selenium WebDriver."""
    options = get_chrome_options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-crash-reporter")
    # Use a large, fixed window size to accommodate both portrait and landscape
    # documents at a high resolution, preventing the need for dynamic resizing.
    options.add_argument("--window-size=2000,3000")
    
    temp_dir = tempfile.mkdtemp()
    os.environ['HOME'] = temp_dir

    user_data_dir = os.path.join(temp_dir, "user-data")
    disk_cache_dir = os.path.join(temp_dir, "cache")
    crash_dumps_dir = os.path.join(temp_dir, "crash-dumps")

    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.add_argument(f"--disk-cache-dir={disk_cache_dir}")
    options.add_argument(f"--crash-dumps-dir={crash_dumps_dir}")

    # Use a persistent cache for WebDriver Manager
    persistent_cache_dir = os.path.join(os.path.expanduser("~"), ".aafai-bus-cache", "drivers")
    os.makedirs(persistent_cache_dir, exist_ok=True)

    chromedriver_log_path = os.path.join(download_dir, "chromedriver.log")
    service = Service(ChromeDriverManager(cache_manager=DriverCacheManager(root_dir=persistent_cache_dir)).install(), service_args=['--verbose', f'--log-path={chromedriver_log_path}'])

    print("Initializing WebDriver...")
    driver = webdriver.Chrome(service=service, options=options)
    
    driver.temp_dir = temp_dir

    return driver, service

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

def _expand_all_folders(driver, debug_mode=False):
    """Iteratively expands all folders on the page."""
    print("Expanding all folders...")
    attempts = 0
    max_attempts = 5 if debug_mode else 1000

    while attempts < max_attempts:
        attempts += 1
        try:
            collapsed_folders = driver.find_elements(By.CSS_SELECTOR, "app-index-list-point.folder:not(.expanded)")
            if not collapsed_folders:
                print("--- No more collapsed folders found. Expansion complete. ---")
                break
            
            folder_to_expand = collapsed_folders[0]
            arrow_icon = folder_to_expand.find_element(By.CSS_SELECTOR, "div[data-e2e='index-arrow-icon']")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", arrow_icon)
            time.sleep(0.5)
            arrow_icon.click()
            
            folder_name = folder_to_expand.find_element(By.CSS_SELECTOR, ".index-description-text").text.strip()
            print(f"Expanded: {folder_name.replace(chr(10), ' ')}")
            time.sleep(1.5)
        except (StaleElementReferenceException, ElementNotInteractableException):
            print("Stale element or not interactable, retrying pass.")
            time.sleep(1)
        except Exception as e:
            print(f"An unexpected error occurred during folder expansion: {e}")
            break
            
    if attempts >= max_attempts:
        print(f"Warning: Reached max expansion attempts ({max_attempts}). The folder tree may be incomplete.")

def _gather_all_items(driver):
    """Gathers all items by scrolling through the virtual list."""
    print("Gathering all items...")
    _scroll_to_top(driver)
    all_items_map = {}
    last_count = -1
    consecutive_no_change = 0
    max_scroll_attempts = 500

    try:
        scroll_viewport = driver.find_element(By.CSS_SELECTOR, "cdk-virtual-scroll-viewport")
    except NoSuchElementException:
        scroll_viewport = None

    for i in range(max_scroll_attempts):
        nodes = driver.find_elements(By.CSS_SELECTOR, "app-index-list-point")
        for node in nodes:
            try:
                data_e2e = node.get_attribute('data-e2e')
                if not data_e2e or 'inbox' in data_e2e or 'trash' in data_e2e or data_e2e in all_items_map:
                    continue
                order_text = node.find_element(By.CSS_SELECTOR, ".index-description-order").text.strip()
                if not order_text: continue
                base_name = node.find_element(By.CSS_SELECTOR, ".index-description-text").text.strip()
                if not base_name: continue
                
                all_items_map[data_e2e] = {
                    "id": data_e2e, "order": order_text, "text": _sanitize_filename(base_name),
                    "is_folder": 'folder' in node.get_attribute('class')
                }
            except (NoSuchElementException, StaleElementReferenceException):
                continue
        
        if len(all_items_map) == last_count:
            consecutive_no_change += 1
        else:
            consecutive_no_change = 0
        last_count = len(all_items_map)

        if consecutive_no_change >= 5:
            print("No new items found after several scrolls. Assuming end of list.")
            break

        if scroll_viewport:
            driver.execute_script("arguments[0].scrollTop += arguments[0].offsetHeight;", scroll_viewport)
        else:
            driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.PAGE_DOWN)
        time.sleep(1.5)

    all_items = list(all_items_map.values())
    print(f"Gathered {len(all_items)} unique items.")
    return all_items

def _scroll_to_top(driver):
    """Scrolls the virtual scroll viewport to the top."""
    try:
        scroll_viewport = driver.find_element(By.CSS_SELECTOR, "cdk-virtual-scroll-viewport")
        driver.execute_script("arguments[0].scrollTop = 0;", scroll_viewport)
    except NoSuchElementException:
        driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(2)

def _process_all_items(driver, items, download_root):
    """Iteratively processes all items to create folders and download documents."""
    _scroll_to_top(driver)
    path_map = {"": download_root}

    sorted_folders = sorted([item for item in items if item['is_folder']], key=lambda x: tuple(map(int, x['order'].split('.'))))
    for item in sorted_folders:
        parent_order = ".".join(item['order'].split('.')[:-1])
        parent_path = path_map.get(parent_order, download_root)
        new_path = os.path.join(parent_path, item['text'])
        os.makedirs(new_path, exist_ok=True)
        path_map[item['order']] = new_path

    sorted_docs = sorted([item for item in items if not item['is_folder']], key=lambda x: tuple(map(int, x['order'].split('.'))))
    for item in sorted_docs:
        parent_order = ".".join(item['order'].split('.')[:-1])
        parent_path = path_map.get(parent_order, download_root)
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
            ActionChains(driver).double_click(element_to_click).perform()
            
            _process_document(driver, pdf_path)
            
            WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "app-index-list-view")))
        except Exception as e:
            print(f"    Could not process document '{item['text']}'. Error: {e}")
            try:
                if driver.find_elements(By.CSS_SELECTOR, "app-document-reader"):
                    close_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-e2e='close'], [aria-label='Close']")))
                    close_button.click()
                WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "app-index-list-view")))
            except Exception as nav_e:
                print(f"    Failed to return to the document list after error. Aborting. Navigation error: {nav_e}")
                raise

def _process_document(driver, pdf_path):
    """
    Captures a document by scrolling through and capturing each page.
    Assumes the browser window is large enough to contain a full page for high-res screenshots.
    """
    print(f"    -> Saving to: {os.path.basename(pdf_path)}")
    temp_img_dir = os.path.join(os.path.dirname(pdf_path), "temp_images_" + os.path.basename(pdf_path))
    os.makedirs(temp_img_dir, exist_ok=True)

    image_files = []

    try:
        viewer = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='doc-reader-document-component']"))
        )
        time.sleep(3) # Allow content to render

        # --- Scroll through and capture all pages ---
        processed_pages = set()
        last_count = -1
        no_new_pages_count = 0
        
        # Scroll to the top of the document viewer before starting
        driver.execute_script("arguments[0].scrollTop = 0;", viewer)
        time.sleep(1)

        while True:
            page_wrappers = viewer.find_elements(By.CSS_SELECTOR, ".page-wrapper")
            
            if not page_wrappers and not processed_pages:
                print("    No pages found in the document.")
                break

            for page in page_wrappers:
                try:
                    page_id = page.get_attribute('data-e2e')
                    if page_id and page_id not in processed_pages:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page)
                        time.sleep(1.5) # Increased wait for page to settle and render fully

                        img_path = os.path.join(temp_img_dir, f"{page_id}.png")
                        page.screenshot(img_path)
                        image_files.append((page_id, img_path))
                        processed_pages.add(page_id)
                        print(f"    Captured page {page_id} ({len(processed_pages)} total)")
                except StaleElementReferenceException:
                    print(f"    Stale element reference for page {page_id}, continuing...")
                    continue
            
            # Check for end of document
            if len(processed_pages) == last_count:
                no_new_pages_count += 1
            else:
                no_new_pages_count = 0
            last_count = len(processed_pages)

            if no_new_pages_count >= 5:
                print("    No new pages found after several scrolls. Assuming end of document.")
                break

            # Scroll down the viewer to load more pages
            driver.execute_script("arguments[0].scrollTop += arguments[0].offsetHeight * 0.8;", viewer)
            time.sleep(2) # Increased wait for scroll to complete and new pages to load

        # --- Assemble PDF ---
        if image_files:
            # Sort images based on the page number in their ID (e.g., 'page-1', 'page-2')
            image_files.sort(key=lambda x: int(re.search(r'(\d+)$', x[0]).group()))
            sorted_image_paths = [p[1] for p in image_files]
            
            valid_images = [p for p in sorted_image_paths if os.path.exists(p) and os.path.getsize(p) > 0]
            if valid_images:
                first_image = Image.open(valid_images[0]).convert('RGB')
                other_images = [Image.open(p).convert('RGB') for p in valid_images[1:]]
                first_image.save(pdf_path, save_all=True, append_images=other_images)
                print(f"    Successfully created PDF with {len(valid_images)} pages.")
            else:
                print("    No valid images were captured.")

    finally:
        # --- Cleanup ---
        shutil.rmtree(temp_img_dir, ignore_errors=True)
        try:
            close_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-e2e='close'], [aria-label='Close']"))
            )
            close_button.click()
        except TimeoutException:
            print("    Close button not found, navigating back.")
            driver.back()
