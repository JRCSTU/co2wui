import os
import re
import unittest
import warnings

import flask
import pytest
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

@pytest.mark.usefixtures("app")
class TestLiveServer:
    def test_000_dummy(self):
        pass

    def test_100_datasync_form(self, driver, live_server, url_for):

        print("Starting datasync download template UI test")
        driver.get(url_for("sync/template-form"))

        elem = driver.find_element_by_tag_name("h1")
        assert elem.text == "Data synchronisation"

        elem = driver.find_element_by_tag_name("h3")
        assert elem.text == "Choose a datasync template type"

        elem = driver.find_element_by_id("cycle")
        assert elem.text == "WLTP\nNEDC"

        elem = driver.find_element_by_id("wltpclass")
        assert elem.text == "Class 1\nClass 2\nClass 3a\nClass 3b"

        # Change to wltp, gearbox should be present
        elem = driver.find_element_by_id("cycle")
        select_element = Select(elem)
        select_element.select_by_value("nedc")
        elem = driver.find_element_by_id("gearbox")
        assert elem.text == "Automatic\nManual"

    def test_110_datasync(self, driver, live_server, url_for):

       print("Starting datasync UI test")
       driver.get(url_for("sync/synchronisation-form"))

       elem = driver.find_element_by_id("file")
       elem.send_keys(os.path.join(os.getcwd(), "test", "datasync.xlsx"))

       elem = driver.find_element_by_id("add-sync-file-form").submit()

       wait = WebDriverWait(driver, 20)
       cond = wait.until(EC.visibility_of_element_located((By.ID, "delete-button")))

       elem = driver.find_element_by_id("synchronise-button")
       assert elem.text == "Synchronise data"

       elem.click()
       WebDriverWait(driver, 20).until(
           EC.text_to_be_present_in_element(
               (By.ID, "sync-feedback"), "1 file has been processed"
           )
       )

    def test_120_delete_file(self, driver, live_server, url_for):

        print("Starting datasync delete file UI test")
        driver.get(url_for("sync/synchronisation-form"))

        src = driver.page_source
        text_found = re.search(r"datasync.xlsx", src)
        assert text_found is not None

        elem = driver.find_element_by_id("delete-button")
        elem.click()

        src = driver.page_source
        text_found = re.search(r"datasync.xlsx", src)
        assert text_found is None

    def test_130_new_sync(self, driver, live_server, url_for):

        print("Starting new synchronisation UI test")
        driver.get(url_for("sync/synchronisation-form"))

        elem = driver.find_element_by_id("file")
        elem.send_keys(os.path.join(os.getcwd(), "test", "datasync.xlsx"))

        elem = driver.find_element_by_id("add-sync-file-form").submit()

        wait = WebDriverWait(driver, 20)
        cond = wait.until(EC.visibility_of_element_located((By.ID, "delete-button")))

        elem = driver.find_element_by_id("synchronise-button")
        assert elem.text == "Synchronise data"

        elem.click()
        WebDriverWait(driver, 20).until(
            EC.text_to_be_present_in_element(
                (By.ID, "sync-feedback"), "1 file has been processed"
            )
        )

        elem = driver.find_element_by_id("synchronise-button")
        assert elem.is_displayed() is not True

        elem = driver.find_element_by_link_text("Synchronise another file")
        elem.click()

        elem = driver.find_element_by_id("synchronise-button")
        assert elem.is_displayed() is True

        # Delete file
        driver.get(url_for("sync/synchronisation-form"))
        elem = driver.find_element_by_id("delete-button")
        elem.click()

        src = driver.page_source
        text_found = re.search(r"datasync.xlsx", src)
        assert text_found is None

    def test_140_datasync_file_other_name(self, driver, live_server, url_for):

        elem = driver.find_element_by_id("file")
        elem.send_keys(os.path.join(os.getcwd(), "test", "datasync-other-name.xlsx"))

        elem = driver.find_element_by_id("add-sync-file-form").submit()

        wait = WebDriverWait(driver, 10)
        cond = wait.until(EC.visibility_of_element_located((By.ID, "delete-button")))

        src = driver.page_source
        text_found = re.search(r"datasync-other-name.xlsx", src)
        assert text_found is not None

        src = driver.page_source
        text_found = re.search(r"datasync.xlsx", src)
        assert text_found is None

        elem = driver.find_element_by_id("delete-button")
        elem.click()

        src = driver.page_source
        text_found = re.search(r"datasync-other-name", src)
        assert text_found is None

    def test_150_datasync_with_empty_file(self, driver, live_server, url_for):

        print("Starting datasync with empty file UI test")
        driver.get(url_for("sync/synchronisation-form"))

        elem = driver.find_element_by_id("file")
        elem.send_keys(os.path.join(os.getcwd(), "test", "datasync-empty.xlsx"))

        driver.implicitly_wait(2)
        elem = driver.find_element_by_id("add-sync-file-form").submit()

        wait = WebDriverWait(driver, 20)
        cond = wait.until(EC.visibility_of_element_located((By.ID, "delete-button")))

        elem = driver.find_element_by_id("synchronise-button")
        assert elem.text == "Synchronise data"

        elem.click()
        WebDriverWait(driver, 5).until(
            EC.text_to_be_present_in_element(
                (By.ID, "logarea"), "Synchronisation failed:"
            )
        )

        elem = driver.find_element_by_id("delete-button")
        elem.click()

        src = driver.page_source
        text_found = re.search(r"datasync-empty", src)
        assert text_found is None

    def test_160_upload_config_file(self, driver, live_server, url_for):

        print("Starting upload config file test")
        driver.get(url_for("conf/configuration-form"))

        elem = driver.find_element_by_tag_name("h1")
        assert elem.text == "Configuration file"

        elem = driver.find_element_by_id("file")
        elem.send_keys(os.path.join(os.getcwd(), "test", "sample.conf.yaml"))

        elem = driver.find_element_by_id("conf-file-form").submit()

        wait = WebDriverWait(driver, 10)
        cond = wait.until(EC.visibility_of_element_located((By.ID, "conf-table")))

        src = driver.page_source
        text_found = re.search(r"conf.yaml", src)
        assert text_found is not None

        text_found = re.search(r"Download", src)
        assert text_found is not None

        text_found = re.search(r"Delete", src)
        assert text_found is not None

        elem = driver.find_element_by_id("delete-button")
        elem.click()

        src = driver.page_source
        text_found = re.search(r"conf.yaml", src)
        assert text_found is None
