import os
import socket
import subprocess
import pytest
from selenium import webdriver
from selenium.webdriver.firefox.options import Options

import co2wui.app

# from https://pytest-flask.readthedocs.io/en/latest/tutorial.html#step-2-configure
@pytest.fixture(scope="session")
def app():
    return co2wui.app.create_app()


@pytest.fixture(scope="session")
def port():
    return co2wui.app.get_free_port()


@pytest.fixture(scope="session")
def url_for(port):
    def _url_for(page=""):
        return f"http://localhost:{port}/{page}"

    return _url_for


# https://github.com/pytest-dev/pytest-flask/issues/54#issuecomment-334154030
@pytest.fixture(scope="session")
def live_server(app, port):
    env = os.environ.copy()
    env["FLASK_APP"] = "co2wui.app"
    server = subprocess.Popen(["flask", "run", "--port", str(port)], env=env)
    try:
        yield server
    finally:
        server.terminate()


## See https://github.com/pytest-dev/pytest-selenium/issues/59
@pytest.fixture(scope="session")
def driver(live_server, url_for):
    opts = Options()
    opts.headless = False

    driver = webdriver.Firefox(options=opts)
    driver.implicitly_wait(2)
    driver.get(url_for())
    elem = driver.find_element_by_id("do-not-show")
    elem.click()

    elem = driver.find_element_by_id("close-hints")
    elem.click()

    try:
        yield driver
    finally:
        driver.quit()
