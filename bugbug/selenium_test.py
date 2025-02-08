from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.firefox import GeckoDriverManager


class PhabricatorScraper:
    def __init__(self):
        driver_path = GeckoDriverManager().install()
        self.service = Service(driver_path)
        self.driver = webdriver.Firefox(service=self.service)
        self.wait = WebDriverWait(self.driver, 10)

    def get_raw_file_content(self, revision_id, first_diff, second_diff, file_path):
        url = (
            f"https://phabricator.services.mozilla.com/"
            f"D{revision_id}?vs={first_diff}&id={second_diff}#toc"
        )
        try:
            self.driver.get(url)

            changesets = self.driver.find_elements(
                By.CSS_SELECTOR,
                ".differential-changeset[data-sigil='differential-changeset']",
            )

            for changeset in changesets:
                path_el = changeset.find_element(
                    By.CSS_SELECTOR, ".differential-changeset-path-name"
                )

                # Check if this is our file
                if path_el.text.strip() == file_path:
                    view_options = changeset.find_element(
                        By.CSS_SELECTOR, "[data-sigil='differential-view-options']"
                    )
                    view_options.click()

                    wait = WebDriverWait(self.driver, 10)
                    show_raw_left = wait.until(
                        EC.element_to_be_clickable(
                            (By.LINK_TEXT, "Show Raw File (Left)")
                        )
                    )

                    old_handles = self.driver.window_handles
                    show_raw_left.click()
                    wait.until(EC.new_window_is_opened(old_handles))

                    new_handles = self.driver.window_handles
                    new_window = [h for h in new_handles if h not in old_handles]
                    if not new_window:
                        return ""

                    self.driver.switch_to.window(new_window[0])

                    pre_element = wait.until(
                        EC.presence_of_element_located((By.TAG_NAME, "pre"))
                    )
                    return pre_element.text

            # If we never found the file
            return ""

        except Exception:
            # Any error (Timeout, NoSuchElement, etc.) => return ""
            return ""

    def close(self):
        # Call this ONCE when totally done
        self.driver.quit()
