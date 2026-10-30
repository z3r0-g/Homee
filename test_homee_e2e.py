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
    # MCP marketplace lives inside the Settings modal → MCPs tab → Marketplace sub-tab
    page.get_by_test_id("settings-btn").click()
    expect(page.locator("#settingsModal")).to_have_class("modal active")
    page.click('.tab-btn[data-tab="mcp"]')
    page.click('.sub-tab[data-subtab="mcps-marketplace"]')
    page.wait_for_timeout(500)
    expect(page.locator(".mcp-card").first).to_be_visible()


def test_marketplace_auth_warnings_and_filters(page):
    page.get_by_test_id("settings-btn").click()
    page.click('.tab-btn[data-tab="mcp"]')
    page.click('.sub-tab[data-subtab="mcps-marketplace"]')
    page.wait_for_timeout(500)
    
    # Check auth warning tag is visible on cards requiring credentials
    expect(page.locator(".auth-warning-tag").first).to_be_visible()

    # Click the "auth required" filter chip
    auth_chip = page.locator('.chip[data-market-chip="auth required"]')
    if auth_chip.is_visible():
        auth_chip.click()
        page.wait_for_timeout(300)
        expect(page.locator(".mcp-card").first).to_be_visible()


def test_one_click_mcp_install(page):
    page.get_by_test_id("settings-btn").click()
    page.click('.tab-btn[data-tab="mcp"]')
    page.click('.sub-tab[data-subtab="mcps-marketplace"]')
    page.wait_for_timeout(500)

    # Find a non-auth card and click install (one click without modal)
    no_auth_card = page.locator(".mcp-card:has(.auth-tag-none)").first
    expect(no_auth_card).to_be_visible()
    install_btn = no_auth_card.locator('button[data-market-action="install"]')
    install_btn.click()
    page.wait_for_timeout(800)

    # Switch to Installed tab to confirm one-click installation
    page.click('.sub-tab[data-subtab="mcps-installed"]')
    page.wait_for_timeout(500)
    expect(page.locator(".market-item.installed").first).to_be_visible()


def test_smithery_sync_buttons(page):
    page.get_by_test_id("settings-btn").click()
    page.click('.tab-btn[data-tab="mcp"]')
    page.click('.sub-tab[data-subtab="mcps-marketplace"]')
    page.wait_for_timeout(300)

    # Sync button in MCP marketplace
    expect(page.locator("#mcpSyncBtn")).to_be_visible()

    # Sync button in Skills marketplace
    page.click('.tab-btn[data-tab="skills"]')
    page.click('.sub-tab[data-subtab="skills-marketplace"]')
    page.wait_for_timeout(300)
    expect(page.locator("#skillSyncBtn")).to_be_visible()


def test_bot_uses_assigned_skill(page):
    # Select or create a bot and send chat
    page.get_by_test_id("new-bot-btn").click()
    page.fill("#newBotName", "Skill Demo Bot")
    page.select_option("#newBotSkill", index=1)
    page.fill("#newBotTaskPrompt", "what is server status")
    page.click("button[type=submit]")
    page.wait_for_timeout(500)

    # Click on the newly created bot to open chat
    page.locator('.bot-item[data-bot-name="Skill Demo Bot"]').click()
    page.wait_for_timeout(500)

    # Confirm bot info displays the assigned skill
    expect(page.locator(".bot-meta")).to_contain_text("Skill:")
    expect(page.locator(".bot-meta")).not_to_contain_text("Skill: none")
