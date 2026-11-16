import logging
import os
import shutil
import sys
from unittest.mock import MagicMock
from src.browser_config import get_headless_status
from src.actions.solve_captcha import solve_captcha

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
from selenium.webdriver.common.action_chains import ActionChains
import tempfile
import subprocess
import threading
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
_CHROME_LAUNCH_LOCK = threading.Lock()
_SEARCH_LOCK = threading.Lock()


def _chrome_options(uc, user_data_dir=None, browser_executable_path=None):
    """Build a new ChromeOptions instance. undetected-chromedriver forbids reusing one."""
    options = uc.ChromeOptions()
    if isinstance(browser_executable_path, str) and browser_executable_path:
        options.binary_location = browser_executable_path
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
    options.add_argument("--window-size=1920,1080")
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument(f"--disk-cache-dir={os.path.join(user_data_dir, 'cache')}")
        options.add_argument(f"--crash-dumps-dir={os.path.join(user_data_dir, 'crash-dumps')}")
    return options


def _driver_cache_dir():
    """Writable cache for the patched chromedriver. On Linux uc otherwise uses ~/.local."""
    path = os.path.join(tempfile.gettempdir(), "undetected_chromedriver")
    os.makedirs(path, exist_ok=True)
    return path


def _clear_driver_cache():
    """Drop a cached chromedriver so the next launch cannot reuse a mismatched binary."""
    cache_dir = _driver_cache_dir()
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as e:
            logging.debug(f"Could not remove cached ChromeDriver file {path}: {e}")


def _launch_chrome(uc, launch_kwargs, profile_dir):
    """Spawn Chrome with a writable home, then restore this process's environment."""
    overrides = {
        "HOME": profile_dir,
        "XDG_CACHE_HOME": os.path.join(profile_dir, "cache"),
        "XDG_CONFIG_HOME": os.path.join(profile_dir, "config"),
        "XDG_DATA_HOME": os.path.join(profile_dir, "local"),
    }
    for path in overrides.values():
        os.makedirs(path, exist_ok=True)
    with _CHROME_LAUNCH_LOCK:
        previous = {key: os.environ.get(key) for key in overrides}
        os.environ.update(overrides)
        uc.Patcher.data_path = _driver_cache_dir()
        try:
            return uc.Chrome(**launch_kwargs)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _detect_chrome_version(uc, error=None):
    """Return Chrome's major version from the launch error or installed binary, if available."""
    version_match = re.search(r'Current browser version is (\d+)', str(error or ""))
    if version_match:
        return int(version_match.group(1))
    try:
        chrome_executable = uc.find_chrome_executable()
        if not isinstance(chrome_executable, str) or not chrome_executable:
            return None
        version_output = subprocess.run(
            [chrome_executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        version_match = re.search(r'(\d+)(?:\.\d+)+', f"{version_output.stdout} {version_output.stderr}")
        return int(version_match.group(1)) if version_match else None
    except Exception as e:
        logging.debug(f"Could not detect the installed Chrome version: {e}")
        return None


def _is_driver_connection_error(error):
    message = f"{type(error).__name__}: {error}".lower()
    return any(indicator in message for indicator in (
        "unable to obtain driver for chrome",
        "connection refused",
        "connection reset",
        "connection aborted",
        "failed to establish a new connection",
        "max retries exceeded",
        "remote end closed",
        "chrome not reachable",
        "session not created",
        "invalid session id",
        "disconnected",
    ))


def _quit_driver(driver):
    if driver is None:
        return
    try:
        driver.quit()
    except Exception as e:
        logging.debug(f"Could not cleanly shut down ChromeDriver: {e}")


def _cleanup_driver(driver):
    if driver is None:
        return
    _quit_driver(driver)
    time.sleep(1)
    temp_dir = getattr(driver, "temp_dir", None)
    if isinstance(temp_dir, str) and temp_dir:
        try:
            shutil.rmtree(temp_dir)
        except OSError as e:
            logging.warning(f"Could not remove temporary directory {temp_dir}: {e}")


def _setup_driver(job_download_dir, download_dir):
    """Configures and returns a Chrome WebDriver instance using undetected-chromedriver."""
    import undetected_chromedriver as uc

    is_headless = get_headless_status()
    original_error = None
    browser_executable = uc.find_chrome_executable()
    if not isinstance(browser_executable, str) or not browser_executable:
        browser_executable = None
    detected_version = _detect_chrome_version(uc)
    driver = None
    temp_dir = None
    for attempt in range(3):
        temp_dir = tempfile.mkdtemp(prefix="semantic-scholar-chrome-")
        launch_options = _chrome_options(uc, temp_dir, browser_executable)
        launch_kwargs = {
            "options": launch_options,
            "headless": is_headless,
            "use_subprocess": True,
        }
        if browser_executable:
            launch_kwargs["browser_executable_path"] = browser_executable
        if detected_version:
            launch_kwargs["version_main"] = detected_version
        try:
            driver = _launch_chrome(uc, launch_kwargs, temp_dir)
            break
        except Exception as e:
            if original_error is None:
                original_error = e
            if "only supports chrome version" in str(e).lower():
                _clear_driver_cache()
            detected_version = _detect_chrome_version(uc, e) or detected_version
            logging.warning(
                "ChromeDriver launch attempt %s of 3 failed: %s",
                attempt + 1,
                e,
            )
            try:
                shutil.rmtree(temp_dir)
            except OSError as cleanup_error:
                logging.debug(f"Could not remove failed Chrome profile {temp_dir}: {cleanup_error}")
            if attempt == 2:
                raise original_error

    if driver is None:
        raise original_error

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


def _element_is_displayed(element):
    try:
        return element.is_displayed()
    except Exception:
        return False


def _button_text(button):
    try:
        text = button.text
        return text.strip().lower() if isinstance(text, str) else ""
    except Exception:
        return ""


def _is_begin_button(button):
    text = _button_text(button)
    if text == "begin" or text.startswith("begin "):
        return True
    try:
        element_id = button.get_attribute("id")
    except Exception:
        element_id = None
    return element_id == "amzn-captcha-verify-button" and text in ("", "begin")


def _find_begin_button(driver):
    try:
        button = driver.execute_script("""
            function textOf(el) {
                return ((el.innerText || el.textContent || '') + '').replace(/\\s+/g, ' ').trim().toLowerCase();
            }
            function walk(root) {
                if (!root || !root.querySelectorAll) return null;
                var byId = root.querySelector('#amzn-captcha-verify-button');
                if (byId) {
                    var label = textOf(byId);
                    if (!label || label === 'begin' || label.indexOf('begin') === 0) return byId;
                }
                var buttons = root.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var label = textOf(buttons[i]);
                    if (label === 'begin' || label.indexOf('begin') === 0) return buttons[i];
                }
                var nodes = root.querySelectorAll('*');
                for (var j = 0; j < nodes.length; j++) {
                    if (nodes[j].shadowRoot) {
                        var found = walk(nodes[j].shadowRoot);
                        if (found) return found;
                    }
                }
                return null;
            }
            return walk(document);
        """)
        if button and _is_begin_button(button):
            return button
    except Exception:
        pass

    try:
        button = driver.find_element(By.ID, "amzn-captcha-verify-button")
        if _is_begin_button(button):
            return button
    except Exception:
        pass
    return None


def _find_captcha_iframe(driver):
    try:
        frames = driver.find_elements(
            By.CSS_SELECTOR,
            "#captcha-container iframe, iframe[src*='captcha'], iframe[title*='captcha'], iframe[name*='captcha']"
        )
        for frame in frames:
            if _element_is_displayed(frame):
                return frame
    except Exception:
        pass
    return None


def _captcha_puzzle_is_rendered(driver):
    if _find_captcha_iframe(driver):
        return True

    try:
        canvases = driver.find_elements(By.CSS_SELECTOR, "#captcha-container canvas, canvas")
        if any(_element_is_displayed(canvas) for canvas in canvases):
            return True
    except Exception:
        pass

    try:
        images = driver.find_elements(By.CSS_SELECTOR, "#captcha-container img")
        for image in images:
            if not _element_is_displayed(image):
                continue
            src = image.get_attribute("src") or ""
            alt = image.get_attribute("alt") or ""
            size = image.size or {}
            if "captcha" in alt.lower() or (
                not src.lower().startswith("data:image/svg+xml")
                and size.get("width", 0) >= 100
                and size.get("height", 0) >= 100
            ):
                return True
    except Exception:
        pass
    return False


def _element_center(driver, element):
    try:
        rect = driver.execute_script("""
            arguments[0].scrollIntoView({block: 'center', inline: 'center'});
            var r = arguments[0].getBoundingClientRect();
            return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height};
        """, element)
        if isinstance(rect, dict):
            return float(rect["x"]), float(rect["y"])
    except Exception:
        return None
    return None


def _find_puzzle_grid(driver, container):
    """Return the image or canvas that holds the tile grid, not the surrounding challenge chrome."""
    try:
        grid = driver.execute_script("""
            var root = arguments[0];
            var nodes = root.querySelectorAll('canvas, img');
            var best = null;
            var bestArea = 0;
            for (var i = 0; i < nodes.length; i++) {
                var node = nodes[i];
                var src = (node.getAttribute('src') || '').toLowerCase();
                if (src.indexOf('data:image/svg') === 0) continue;
                var rect = node.getBoundingClientRect();
                var area = rect.width * rect.height;
                if (rect.width >= 120 && rect.height >= 120 && area > bestArea) {
                    best = node;
                    bestArea = area;
                }
            }
            return best;
        """, container)
        if isinstance(getattr(grid, "tag_name", None), str):
            return grid
    except Exception as e:
        logging.debug(f"Could not locate the CAPTCHA image grid: {e}")
    return container


def _frame_viewport_offset(driver, frame):
    try:
        rect = driver.execute_script("""
            var rect = arguments[0].getBoundingClientRect();
            return {x: rect.left, y: rect.top};
        """, frame)
        if isinstance(rect, dict):
            return float(rect["x"]), float(rect["y"])
    except Exception as e:
        logging.debug(f"Could not determine CAPTCHA iframe position: {e}")
    return 0.0, 0.0


def _offset_for_visible_click(driver, frame, frame_offset, local_x, local_y):
    """Scroll the captcha frame so a tile click is inside the browser viewport."""
    if frame is None:
        return frame_offset
    top_x = local_x + frame_offset[0]
    top_y = local_y + frame_offset[1]
    try:
        size = driver.get_window_size()
        if not isinstance(size, dict):
            return frame_offset
        width = float(size.get("width") or 0)
        height = float(size.get("height") or 0)
    except Exception:
        return frame_offset
    if width <= 0 or height <= 0:
        return frame_offset
    if 5 <= top_x <= width - 5 and 5 <= top_y <= height - 5:
        return frame_offset
    try:
        driver.switch_to.default_content()
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
            frame,
        )
        frame_offset = _frame_viewport_offset(driver, frame)
        driver.switch_to.frame(frame)
    except Exception as e:
        logging.debug(f"Could not scroll the CAPTCHA tile into view: {e}")
        try:
            driver.switch_to.frame(frame)
        except Exception:
            pass
    return frame_offset


def _dispatch_trusted_click(driver, x, y, coordinate_offset=(0.0, 0.0)):
    x += coordinate_offset[0]
    y += coordinate_offset[1]
    try:
        for event_type, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                "type": event_type,
                "x": x,
                "y": y,
                "button": "left",
                "buttons": buttons,
                "clickCount": 1,
            })
        return True
    except Exception as e:
        logging.debug(f"Trusted mouse click failed: {e}")
        return False


def _trusted_click(driver, element, coordinate_offset=(0.0, 0.0)):
    center = _element_center(driver, element)
    if center:
        x, y = center
        if _dispatch_trusted_click(driver, x, y, coordinate_offset):
            return True

    try:
        ActionChains(driver).move_to_element(element).click().perform()
        return True
    except Exception:
        try:
            element.click()
            return True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", element)
                return True
            except Exception:
                return False


def _click_begin_and_wait(driver):
    begin_button = None
    for _ in range(8):
        begin_button = _find_begin_button(driver)
        if begin_button:
            break
        time.sleep(0.5)
    if not begin_button:
        logging.info("Security check is visible, but the Begin button was not found.")
        return

    for attempt in range(3):
        begin_button = _find_begin_button(driver)
        if not begin_button and attempt == 0:
            return
        if begin_button:
            logging.info("Found 'Begin' button for AWS WAF CAPTCHA. Clicking it with a trusted mouse event...")
            if not _trusted_click(driver, begin_button):
                return

        for _ in range(12):
            if _captcha_puzzle_is_rendered(driver):
                return
            time.sleep(0.5)


def _solve_captcha_challenge(driver):
    captcha_frame = _find_captcha_iframe(driver)
    switched_to_frame = False
    frame_offset = (0.0, 0.0)
    if captcha_frame:
        frame_offset = _frame_viewport_offset(driver, captcha_frame)
        try:
            driver.switch_to.frame(captcha_frame)
            switched_to_frame = True
        except Exception as e:
            frame_offset = (0.0, 0.0)
            logging.warning(f"Could not switch to CAPTCHA iframe: {e}")

    try:
        screenshot_path = None
        captcha_result = None
        captcha_elem = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                screenshot_path = tmp_img.name

            try:
                captcha_elem = driver.find_element(By.ID, "captcha-container")
            except Exception:
                if switched_to_frame:
                    try:
                        captcha_elem = driver.find_element(By.TAG_NAME, "body")
                    except Exception:
                        pass

            if captcha_elem:
                captcha_elem = _find_puzzle_grid(driver, captcha_elem)
                try:
                    captcha_elem.screenshot(screenshot_path)
                except Exception:
                    driver.save_screenshot(screenshot_path)
            else:
                driver.save_screenshot(screenshot_path)

            logging.info(f"Calling solve_captcha action for detected CAPTCHA image: {screenshot_path}")
            captcha_result = solve_captcha(screenshot_path)
            logging.info(f"solve_captcha action completed with result: {captcha_result}")
        except Exception as e:
            logging.warning(f"Error calling solve_captcha action: {e}")
        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except Exception:
                    pass

        if isinstance(captcha_result, dict) and "matrix" in captcha_result:
            matrix = captcha_result.get("matrix", [])
            rows = captcha_result.get("rows") or len(matrix)
            cols = captcha_result.get("cols") or (len(matrix[0]) if matrix and len(matrix) > 0 else 0)

            if rows > 0 and cols > 0 and captcha_elem:
                logging.info(f"Applying CAPTCHA tile clicks for grid {rows}x{cols}...")
                for r in range(rows):
                    for c in range(cols):
                        if r < len(matrix) and c < len(matrix[r]) and matrix[r][c]:
                            logging.info(f"Clicking CAPTCHA tile at row {r}, col {c}")
                            try:
                                tile_point = driver.execute_script("""
                                    var container = arguments[0];
                                    var r = arguments[1];
                                    var c = arguments[2];
                                    var rows = arguments[3];
                                    var cols = arguments[4];
                                    container.scrollIntoView({block: 'center', inline: 'center'});
                                    var rect = container.getBoundingClientRect();
                                    var clickX = rect.left + (c + 0.5) * (rect.width / cols);
                                    var clickY = rect.top + (r + 0.5) * (rect.height / rows);
                                    if (clickY < 8 || clickY > window.innerHeight - 8) {
                                        window.scrollBy(0, clickY - window.innerHeight / 2);
                                        rect = container.getBoundingClientRect();
                                        clickX = rect.left + (c + 0.5) * (rect.width / cols);
                                        clickY = rect.top + (r + 0.5) * (rect.height / rows);
                                    }
                                    return {
                                        x: clickX,
                                        y: clickY,
                                        target: document.elementFromPoint(clickX, clickY) || container
                                    };
                                """, captcha_elem, r, c, rows, cols)
                                if isinstance(tile_point, dict):
                                    try:
                                        tile_x = float(tile_point["x"])
                                        tile_y = float(tile_point["y"])
                                    except (KeyError, TypeError, ValueError):
                                        tile_x = tile_y = None
                                    if tile_x is not None and tile_y is not None:
                                        frame_offset = _offset_for_visible_click(
                                            driver, captcha_frame, frame_offset, tile_x, tile_y
                                        )
                                        if not _dispatch_trusted_click(driver, tile_x, tile_y, frame_offset):
                                            tile = tile_point.get("target")
                                            if tile:
                                                try:
                                                    ActionChains(driver).move_to_element(tile).click().perform()
                                                except Exception:
                                                    tile.click()
                                else:
                                    # Keep a DOM-event fallback for drivers that cannot report element coordinates.
                                    driver.execute_script("""
                                        var container = arguments[0];
                                        var r = arguments[1];
                                        var c = arguments[2];
                                        var rows = arguments[3];
                                        var cols = arguments[4];
                                        var rect = container.getBoundingClientRect();
                                        var x = rect.left + (c + 0.5) * (rect.width / cols);
                                        var y = rect.top + (r + 0.5) * (rect.height / rows);
                                        var elem = document.elementFromPoint(x, y) || container;
                                        ['mousedown', 'mouseup', 'click'].forEach(function(type) {
                                            elem.dispatchEvent(new MouseEvent(type, {
                                                bubbles: true, cancelable: true, view: window,
                                                clientX: x, clientY: y
                                            }));
                                        });
                                    """, captcha_elem, r, c, rows, cols)
                                time.sleep(1)
                            except Exception as tile_err:
                                logging.warning(f"Could not click tile ({r}, {c}): {tile_err}")

            try:
                verify_button = None
                for button_id in ["amzn-captcha-verify-button", "amzn-captcha-submit-button"]:
                    try:
                        button = driver.find_element(By.ID, button_id)
                        if _element_is_displayed(button) and _button_text(button) != "begin":
                            verify_button = button
                            break
                    except Exception:
                        pass
                if not verify_button:
                    try:
                        buttons = driver.find_elements(
                            By.CSS_SELECTOR,
                            ".amzn-captcha-verify-button, .amzn-captcha-submit-button, button[type='submit']"
                        )
                        for button in buttons:
                            if _element_is_displayed(button) and _button_text(button) != "begin":
                                verify_button = button
                                break
                    except Exception:
                        pass

                if verify_button:
                    logging.info("Clicking CAPTCHA verify/submit button...")
                    _trusted_click(driver, verify_button, frame_offset)
                    time.sleep(2)
            except Exception as sub_err:
                logging.warning(f"Error submitting CAPTCHA verification: {sub_err}")
    finally:
        if switched_to_frame:
            try:
                driver.switch_to.default_content()
            except Exception as e:
                logging.debug(f"Could not restore the default document after CAPTCHA handling: {e}")


def _captcha_still_present(driver, bot_indicators):
    try:
        page_source = driver.page_source or ""
    except Exception:
        return False
    if not isinstance(page_source, str):
        return False
    return any(indicator.lower() in page_source.lower() for indicator in bot_indicators)


def _handle_security_check(driver, timeout=90):
    """
    Checks if an AWS WAF CAPTCHA / bot challenge page is displayed.
    Automatically clicks 'Begin' (#amzn-captcha-verify-button) if present to open the interactive puzzle.
    Calls solve_captcha action to process the CAPTCHA image and clicks selected grid tiles.
    If a wrong answer shows a new puzzle, solve_captcha is called again until the challenge clears.
    In non-headless mode, waits for the user to complete the puzzle until the page redirects back.
    In headless mode, raises an exception if unresolved.
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

            deadline = time.monotonic() + timeout
            attempts = 0
            captcha_still_present = True
            while captcha_still_present and attempts < 5 and time.monotonic() < deadline:
                _click_begin_and_wait(driver)
                _solve_captcha_challenge(driver)
                attempts += 1
                captcha_still_present = _captcha_still_present(driver, bot_indicators)
                if captcha_still_present and attempts < 5 and time.monotonic() < deadline:
                    logging.info("CAPTCHA is still present after attempt %s. Solving the next puzzle.", attempts)
                    time.sleep(2)

            if captcha_still_present:
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
            else:
                logging.info("CAPTCHA / Security check resolved automatically.")
    except TimeoutException:
        raise RuntimeError(f"Timed out waiting {timeout}s for AWS WAF CAPTCHA to be resolved.")
    except Exception as e:
        if "blocked the request" in str(e):
            raise
        raise RuntimeError(f"Unable to check Semantic Scholar security verification: {e}") from e


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
        _handle_security_check(driver)
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
        if _is_driver_connection_error(e):
            raise
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


def _article_identity_values(article):
    link = str(article.get("link") or "").strip()
    title = " ".join(str(article.get("title") or "").split()).casefold()
    return link, title


def _run_search(driver, job_id, query_params, fetch_author_details, max_articles,
                relevant_author_query, all_results, author_profile_cache):
    matched_authors = []
    seen_links = set()
    seen_titles = set()
    for article in all_results:
        link, title = _article_identity_values(article)
        if link:
            seen_links.add(link)
        if title:
            seen_titles.add(title)
    page = 1
    total_estimated_results = float('inf')
    estimated_articles = 0
    estimated_citations = 0

    search_url = _build_semantic_scholar_url(query_params)
    logging.info(f"Navigating to Semantic Scholar URL: {search_url}")
    try:
        driver.get(search_url)
    except TimeoutException:
        logging.warning("Initial page load timed out. The page might be partially loaded.")

    _handle_security_check(driver)

    try:
        wait = WebDriverWait(driver, 5)
        cookie_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-test-id="cookie-banner__dismiss-btn"]')))
        logging.info("Cookie banner found. Clicking 'ACCEPT & CONTINUE'.")
        cookie_button.click()
        time.sleep(2)
    except TimeoutException:
        logging.info("Cookie banner not found or not clickable within the timeout period.")
    except Exception as e:
        if _is_driver_connection_error(e):
            raise
        logging.info("Cookie banner could not be dismissed: %s", e)

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
                    link, title = _article_identity_values(parsed_article)
                    if (link and link in seen_links) or (title and title in seen_titles):
                        logging.info("Skipping duplicate Semantic Scholar article: %s", parsed_article.get("title"))
                        continue
                    all_results.append(parsed_article)
                    if link:
                        seen_links.add(link)
                    if title:
                        seen_titles.add(title)
            except Exception as e:
                if _is_driver_connection_error(e):
                    raise
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
    return {
        'job_id': job_id,
        'status': 'Completed',
        'result': {
            'search_query': query_params,
            'total_results_scraped': len(all_results),
            'estimated_article_count': estimated_articles,
            'estimated_citation_count': estimated_citations,
            'matched_authors': matched_authors,
            'articles': all_results,
        },
    }


def execute(job_id, params, download_dir, write_result_to_outbound):
    """Run a Semantic Scholar search and send its result to the outbound queue."""
    logging.info(f"Executing search_semantic_scholar for job {job_id} with params: {json.dumps(params, indent=2)}")
    if not _SEARCH_LOCK.acquire(blocking=False):
        logging.info("Another Semantic Scholar search is running; job %s is waiting.", job_id)
        _SEARCH_LOCK.acquire()
    try:
        _execute_search(job_id, params, download_dir, write_result_to_outbound)
    finally:
        _SEARCH_LOCK.release()


def _execute_search(job_id, params, download_dir, write_result_to_outbound):
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

    try:
        author_profile_cache = {}
        for attempt in range(3):
            driver = None
            try:
                driver = _setup_driver(job_download_dir, download_dir)
                result = _run_search(
                    driver,
                    job_id,
                    query_params,
                    fetch_author_details,
                    max_articles,
                    relevant_author_query,
                    all_results,
                    author_profile_cache,
                )
                break
            except Exception as e:
                if not _is_driver_connection_error(e):
                    raise
                logging.warning(
                    "ChromeDriver connection failed during Semantic Scholar search (attempt %s of 3): %s",
                    attempt + 1,
                    e,
                )
                _cleanup_driver(driver)
                driver = None
                if attempt < 2:
                    continue
                if not all_results:
                    raise
                all_results.sort(key=lambda article: article.get('citations', 0), reverse=True)
                result = {
                    'job_id': job_id,
                    'status': 'Completed',
                    'warning': f"ChromeDriver connection failed after collecting {len(all_results)} articles; returning partial results. Last error: {e}",
                    'result': {
                        'search_query': query_params,
                        'total_results_scraped': len(all_results),
                        'estimated_article_count': 0,
                        'estimated_citation_count': 0,
                        'matched_authors': [],
                        'articles': all_results,
                    },
                }
    except Exception as e:
        logging.error(f"An error occurred during Semantic Scholar search for job {job_id}: {e}", exc_info=True)
        result = {'job_id': job_id, 'status': 'failed', 'error': str(e)}
    finally:
        _cleanup_driver(driver)
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
