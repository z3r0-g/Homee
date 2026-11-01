from types import SimpleNamespace

import requests
from playwright.sync_api import expect


def _patch_ollama(monkeypatch, reply="e2e reply"):
    """Patch ollama.chat for the in-process servers (no real LLM needed)."""
    import ollama

    def _chat(model=None, messages=None, tools=None, **kwargs):
        return SimpleNamespace(
            message=SimpleNamespace(content=reply, tool_calls=[], role="assistant"))

    monkeypatch.setattr(ollama, "chat", _chat)


def _create_bot_via_api(base_url, name):
    resp = requests.post(f"{base_url}/api/bots", json={"name": name, "enabled": False}, timeout=10)
    resp.raise_for_status()
    return resp.json()["bot"]["id"]


def _delete_bot_via_api(base_url, bot_id):
    requests.delete(f"{base_url}/api/bots/{bot_id}", timeout=10)


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
    # Assign a skill via the multi-skill picker (marketplace-style add button)
    first_add = page.locator('#newBotSkillsPicker [data-picker-toggle]').first
    expect(first_add).to_be_visible()
    skill_name = page.locator('#newBotSkillsPicker .market-item-title').first.inner_text()
    first_add.click()
    expect(page.locator('#newBotSkillsPicker .picker-chip')).to_have_count(1)
    page.fill("#newBotTaskPrompt", "what is server status")
    page.click("button[type=submit]")
    page.wait_for_timeout(500)

    # Click on the newly created bot to open chat
    page.locator('.bot-item[data-bot-name="Skill Demo Bot"]').click()
    page.wait_for_timeout(500)

    # Confirm bot info displays the assigned skill
    expect(page.locator(".bot-meta")).to_contain_text("Skills:")
    expect(page.locator(".bot-meta")).to_contain_text(skill_name)
    expect(page.locator(".bot-meta")).not_to_contain_text("Skills: none")


def test_bot_multiple_skills_and_mcps(page, base_url):
    """Bots are no longer 1:1 with skills: assign several skills + MCPs."""
    page.get_by_test_id("new-bot-btn").click()
    page.fill("#newBotName", "Multi Skill Bot")

    skills_picker = page.locator("#newBotSkillsPicker")
    toggles = skills_picker.locator("[data-picker-toggle]")
    expect(toggles.nth(1)).to_be_visible()
    name1 = skills_picker.locator(".market-item-title").nth(0).inner_text()
    name2 = skills_picker.locator(".market-item-title").nth(1).inner_text()
    toggles.nth(0).click()
    toggles.nth(1).click()
    expect(skills_picker.locator(".picker-chip")).to_have_count(2)

    # MCP picker lists installed MCPs; add the first if any are installed
    mcps_picker = page.locator("#newBotMcpsPicker")
    mcp_count = 0
    if mcps_picker.locator("[data-picker-toggle]").count() > 0:
        mcps_picker.locator("[data-picker-toggle]").first.click()
        mcp_count = 1
        expect(mcps_picker.locator(".picker-chip")).to_have_count(1)

    # Remove one skill via its chip X, then re-add it
    skills_picker.locator("[data-picker-remove]").first.click()
    expect(skills_picker.locator(".picker-chip")).to_have_count(1)
    skills_picker.locator("[data-picker-toggle]").first.click()
    expect(skills_picker.locator(".picker-chip")).to_have_count(2)

    page.click("button[type=submit]")
    page.wait_for_timeout(500)

    page.locator('.bot-item[data-bot-name="Multi Skill Bot"]').click()
    page.wait_for_timeout(500)
    meta = page.locator(".bot-meta")
    expect(meta).to_contain_text(name1)
    expect(meta).to_contain_text(name2)
    expect(meta).to_contain_text(f"MCPs: {mcp_count}")

    # No task prompt -> Run Task disabled, adhoc chat still available
    expect(page.locator("#runTaskBtn")).to_be_disabled()
    expect(page.locator("#userMessage")).to_be_enabled()

    # Edit Bot modal restores the multi-selection
    page.locator('[data-bot-action="edit"]').click()
    expect(page.locator("#editBotSkillsPicker .picker-chip")).to_have_count(2)
    expect(page.locator("#editBotMcpsPicker .picker-chip")).to_have_count(mcp_count)
    page.click("#editBotModal .close-modal")


def test_file_attach_chip_and_send(page, monkeypatch, base_url):
    """PLAN.md 1.1: paperclip → chip with filename + size + remove X → send."""
    _patch_ollama(monkeypatch)
    bot_id = _create_bot_via_api(base_url, "File Bot E2E")
    try:
        page.reload(wait_until="networkidle")
        page.locator('.bot-item[data-bot-name="File Bot E2E"]').click()
        page.wait_for_timeout(300)

        # Attach a text file via the hidden input (paperclip opens it).
        page.set_input_files("#fileAttachInput", {
            "name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello from e2e",
        })
        chip = page.locator("#attachedFileBar")
        expect(chip).to_be_visible()
        expect(chip).to_contain_text("notes.txt")
        expect(chip).to_contain_text("14 B")

        # Remove X clears the chip.
        chip.locator("#detachFileBtn").click()
        expect(page.locator("#attachedFileBar")).to_have_count(0)

        # Re-attach and send: reply renders and the chip clears after send.
        page.set_input_files("#fileAttachInput", {
            "name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello from e2e",
        })
        expect(page.locator("#attachedFileBar")).to_be_visible()
        page.fill("#userMessage", "summarize this file")
        page.click(".chat-composer .btn-save")
        expect(page.locator(".message.bot .message-content").last).to_contain_text("e2e reply", timeout=15000)
        expect(page.locator("#attachedFileBar")).to_have_count(0)
    finally:
        _delete_bot_via_api(base_url, bot_id)


def test_search_across_chats(page, monkeypatch, base_url):
    """PLAN.md 1.2: sidebar search finds a message and opens the bot at it."""
    _patch_ollama(monkeypatch)
    bot_id = _create_bot_via_api(base_url, "Search Bot E2E")
    try:
        resp = requests.post(
            f"{base_url}/api/bots/{bot_id}/chat",
            json={"message": "the quixotic aardvark e2e"}, timeout=15)
        resp.raise_for_status()

        page.reload(wait_until="networkidle")
        page.fill("#chatSearchInput", "aardvark")
        page.wait_for_timeout(600)  # 200ms debounce + fetch
        result = page.locator(".search-result").first
        expect(result).to_be_visible()
        expect(result).to_contain_text("Search Bot E2E")
        expect(result).to_contain_text("aardvark")

        result.click()
        page.wait_for_timeout(300)
        # Chat opens on the matching bot with the match highlighted.
        expect(page.locator(".bot-info .bot-meta")).to_be_visible()
        expect(page.locator(".message.search-hit")).to_be_visible()
        expect(page.locator(".message.search-hit")).to_contain_text("aardvark")
    finally:
        _delete_bot_via_api(base_url, bot_id)


def test_new_bot_mcp_picker_fresh_without_reload(page, base_url):
    """MCPs installed after page load appear in the New Bot picker — the
    modal refreshes its options on every open (no page refresh needed)."""
    resp = requests.post(f"{base_url}/api/mcps", json={
        "name": "E2E Fresh MCP", "endpoint": "http://example.com", "method": "GET",
    }, timeout=10)
    resp.raise_for_status()
    mcp_id = resp.json()["mcp"]["id"]
    try:
        # The page loaded before this MCP existed; opening the modal must
        # still list it.
        page.get_by_test_id("new-bot-btn").click()
        item = page.locator('#newBotMcpsPicker .picker-item', has_text="E2E Fresh MCP")
        expect(item).to_be_visible()
        item.locator("[data-picker-toggle]").click()
        expect(page.locator('#newBotMcpsPicker .picker-chip')).to_have_count(1)
        page.click("#newBotModal .close-modal")
    finally:
        requests.delete(f"{base_url}/api/mcps/{mcp_id}", timeout=10)
