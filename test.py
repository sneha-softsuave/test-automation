"""
Playwright Test Suite: Emergex Automation Test Cases.xlsx
Base URL: https://dev-emergex.zapptor.com
Generated: 2026-01-27 18:43:41
Total Test Cases: 1
"""

import pytest
from playwright.sync_api import Page, expect


# Test Data
BASE_URL = "https://dev-emergex.zapptor.com"
TEST_EMAIL = "alicej@example.com"
TEST_PASSWORD = "123456"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
    }


def test_tc_001(page: Page):
    """
    Test ID: TC_001
    Verify Successful Login and Dashboard Navigation
    """

    # Step 1: Launch the web application using the following URL...
    page.goto("https://dev-emergex.zapptor.com")
    page.wait_for_load_state("networkidle")

    # Step 2: Verify that the Login page is displayed by validat...
    expect(page).to_have_url("https://dev-emergex.zapptor.com/login")

    # Step 3: Enter a valid email address in the Email field on ...
    page.get_by_label("Email").fill("alicej@example.com")

    # Step 4: Enter a valid password in the Password field on th...
    page.get_by_label("Password").fill("123456")

    # Step 5: Click on the Login button.
    page.get_by_role("button", name="Login").click()

    # Step 6: Verify that a success toast message is displayed.
    # Wait for toast message
    expect(page.locator(".toast, .Toastify, [role=\"alert\"]").first).to_contain_text("Login successful", timeout=10000)

    # Step 7: Verify that the user is successfully navigated to ...
    # No specific assertion defined
    pass

    # Step 8: Verify that the Dashboard page heading is displaye...
    expect(page.get_by_role("heading", name="Dashboard")).to_contain_text("Dashboard")


test_tc_001()