from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
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

    # def get_raw_file_content(self, revision_id, first_diff, second_diff, file_path):
    #     url = (
    #         f"https://phabricator.services.mozilla.com/"
    #         f"D{revision_id}?vs={first_diff}&id={second_diff}#toc"
    #     )
    #     try:
    #         self.driver.get(url)

    #         changesets = self.driver.find_elements(
    #             By.CSS_SELECTOR,
    #             ".differential-changeset[data-sigil='differential-changeset']",
    #         )

    #         for changeset in changesets:
    #             path_el = changeset.find_element(
    #                 By.CSS_SELECTOR, ".differential-changeset-path-name"
    #             )

    #             # Check if this is our file
    #             if path_el.text.strip() == file_path:
    #                 view_options = changeset.find_element(
    #                     By.CSS_SELECTOR, "[data-sigil='differential-view-options']"
    #                 )
    #                 view_options.click()

    #                 wait = WebDriverWait(self.driver, 10)
    #                 show_raw_left = wait.until(
    #                     EC.element_to_be_clickable(
    #                         (By.LINK_TEXT, "Show Raw File (Left)")
    #                     )
    #                 )

    #                 # Store original window handle
    #                 original_window = self.driver.current_window_handle
    #                 old_handles = self.driver.window_handles

    #                 # Click the link to open the new tab
    #                 show_raw_left.click()
    #                 wait.until(EC.new_window_is_opened(old_handles))

    #                 # Identify the new tab
    #                 new_handles = self.driver.window_handles
    #                 new_window = [h for h in new_handles if h != original_window]
    #                 if not new_window:
    #                     print("No new tab opened.")
    #                     return ""

    #                 # Switch to the new tab
    #                 self.driver.switch_to.window(new_window[0])

    #                 # Close the old tab immediately
    #                 self.driver.switch_to.window(original_window)
    #                 self.driver.close()

    #                 # Switch back to the new tab (now the only tab open)
    #                 self.driver.switch_to.window(new_window[0])

    #                 # Wait for raw file content
    #                 pre_element = wait.until(
    #                     EC.presence_of_element_located((By.TAG_NAME, "pre"))
    #                 )

    #                 return pre_element.text

    #         # If we never found the file
    #         print("No file found.")
    #         return ""

    #     except Exception as e:
    #         print(f"Exception occurred: {e}")
    #         return ""

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
                    try:
                        view_options = changeset.find_element(
                            By.CSS_SELECTOR, "[data-sigil='differential-view-options']"
                        )
                        view_options.click()
                    except NoSuchElementException:
                        print(f"Revision {revision_id}: View Options button not found.")
                        return ""

                    wait = WebDriverWait(self.driver, 10)
                    try:
                        show_raw_left = wait.until(
                            EC.element_to_be_clickable(
                                (By.LINK_TEXT, "Show Raw File (Left)")
                            )
                        )

                        # Check if the button is greyed out
                        if not show_raw_left.is_enabled():
                            print(
                                f"Revision {revision_id}: 'Show Raw File (Left)' button is greyed out."
                            )
                            return ""

                    except TimeoutException:
                        print(
                            f"Revision {revision_id}: 'Show Raw File (Left)' button not found."
                        )
                        return ""

                    # Store original window handle
                    original_window = self.driver.current_window_handle
                    old_handles = self.driver.window_handles

                    # Click the link to open the new tab
                    show_raw_left.click()
                    wait.until(EC.new_window_is_opened(old_handles))

                    # Identify the new tab
                    new_handles = self.driver.window_handles
                    new_window = [h for h in new_handles if h != original_window]
                    if not new_window:
                        print(f"Revision {revision_id}: No new tab opened.")
                        return ""

                    # Switch to the new tab
                    self.driver.switch_to.window(new_window[0])

                    # Close the old tab immediately
                    self.driver.switch_to.window(original_window)
                    self.driver.close()

                    # Switch back to the new tab (now the only tab open)
                    self.driver.switch_to.window(new_window[0])

                    # Wait for raw file content
                    pre_element = wait.until(
                        EC.presence_of_element_located((By.TAG_NAME, "pre"))
                    )

                    return pre_element.text

            # If we never found the file
            print(f"Revision {revision_id}: No matching file found.")
            return ""

        except Exception as e:
            print(f"Revision {revision_id}: Exception occurred: {e}")
            return ""

    def close(self):
        # Call this ONCE when totally done
        self.driver.quit()


# scraper = PhabricatorScraper()
# print(scraper.get_raw_file_content(98508, 373737, 374046, "js/src/jit/VMFunctions.cpp"))
