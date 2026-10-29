from playwright.sync_api import expect


def test_homepage_loads(page):
    expect(page).to_have_title("Homee AI Agent Platform")
    expect(page.get_by_test_id("new-bot-btn")).to_be_visible()


def test_create_bot_appears_in_sidebar(page):
    page.get_by_test_id("new-bot-btn").click()
    page.fill("#newBotName", "E2E Bot")
    page.fill("#newBotTaskPrompt", "check disk space")
    page.click("button[type=submit]")
    # bot list refreshes
    page.wait_for_timeout(500)
    expect(page.get_by_test_id("bot-item").first).to_be_visible()
    expect(page.get_by_test_id("bot-item").first).to_contain_text("E2E Bot")


def test_settings_modal_opens(page):
    page.get_by_test_id("settings-btn").click()
    expect(page.locator("#settingsModal")).to_have_class("modal active")
    page.click("#settingsModal .close-modal")
    expect(page.locator("#settingsModal")).not_to_have_class("modal active")


def test_marketplace_loads(page):
    # MCP marketplace lives inside the Settings modal → MCPs tab.
    # Cards are rendered by JS into #mcpGrid as .mcp-card elements.
    page.get_by_test_id("settings-btn").click()
    expect(page.locator("#settingsModal")).to_have_class("modal active")
    page.click('.tab-btn[data-tab="mcp"]')
    page.wait_for_timeout(500)
    expect(page.locator(".mcp-card").first).to_be_visible()
