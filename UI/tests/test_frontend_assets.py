
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent
CSS_PATH = BASE_DIR / 'UI' / 'static' / 'app.css'
JS_PATH = BASE_DIR / 'UI' / 'static' / 'app.js'
HTML_PATH = BASE_DIR / 'UI' / 'templates' / 'app.html'


def test_app_css_exists_and_nonempty():
    assert CSS_PATH.exists(), f'Missing {CSS_PATH}'
    content = CSS_PATH.read_text(encoding='utf-8')
    assert len(content) > 5000, 'app.css is too small'
    assert content.count(chr(123)) == content.count(chr(125)), 'Unbalanced CSS braces'


def test_app_css_mobile_ux():
    content = CSS_PATH.read_text(encoding='utf-8')
    required = {
        'safe-area support': 'env(safe-area-inset' in content,
        'mobile sidebar toggle': 'mobile-expanded' in content,
        'sidebar overlay': 'sidebar-overlay' in content,
        'sidebar toggle button': 'sidebar-toggle' in content,
        'touch targets (44px)': '44px' in content,
        'container units': 'vw' in content,
        'focus visible': 'focus-visible' in content,
        'reduced motion': 'prefers-reduced-motion' in content,
        'dark theme': 'prefers-color-scheme' in content,
        'backdrop filter': 'backdrop-filter' in content,
        'min-height utility': 'min-height: 44px' in content,
        'sidebar drawer': 'translateX' in content,
        'modal above sidebar': 'z-index: 1101' in content,
        'sidebar-close hidden desktop': '.sidebar-close {\n    display: none' in content,
        'header-status hidden mobile': '.header-actions .header-status' in content,
    }
    for name, ok in required.items():
        assert ok, f'app.css missing required rule: {name}'


def test_app_js_exists_and_nonempty():
    assert JS_PATH.exists(), f'Missing {JS_PATH}'
    content = JS_PATH.read_text(encoding='utf-8')
    assert len(content) > 50000, 'app.js is too small'
    assert 'function' in content
    assert 'document.getElementById' in content


def test_app_js_frontend_features():
    content = JS_PATH.read_text(encoding='utf-8')
    required = {
        'sidebar toggle': 'sidebarToggleBtn' in content,
        'sidebar overlay': 'sidebarOverlay' in content,
        'sidebar drawer toggle': 'toggleSidebar' in content,
        'skills pill': 'skillsPill' in content,
        'mcp endpoint resolution': 'Resolving' in content,
        'no url prompt': 'endpoint not found in catalogue' in content,
        'leaderboard install handler': "data-skill-install" in content,
        'sidebar close on modal': 'toggleSidebar(false)' in content,
        'mcp status load': 'loadMcpStatus' in content,
        'marketplace import': 'Import' in content,
        'marketplace use': 'Use' in content,
        'mobile import loading': 'Importing' in content,
        'skill install loading': 'Installing' in content,
        'escapeHtml': 'escapeHtml' in content,
        'init': 'async function init' in content,
    }
    for name, ok in required.items():
        assert ok, f'app.js missing required feature: {name}'


def test_app_html_frontend_structure():
    content = HTML_PATH.read_text(encoding='utf-8')
    required = {
        'viewport meta': 'name="viewport"' in content,
        'sidebar toggle button': 'sidebar-toggle' in content,
        'sidebar overlay': 'sidebar-overlay' in content,
        'Skills pill': 'skillsPill' in content,
        'LLM status pill': 'llmStatusPill' in content,
        'MCP status pill': 'mcpStatusPill' in content,
        'dialog role': 'role="dialog"' in content,
        'chat-area': 'chat-area' in content,
        'sidebar': 'sidebar' in content,
        'topbar': 'topbar' in content,
        'app-container': 'app-container' in content,
        'new bot modal': 'newBotModal' in content,
        'settings modal': 'settingsModal' in content,
        'pull modal': 'pullModal' in content,
        'mcp grid': 'mcpGrid' in content,
        'skill list': 'skillList' in content,
        'leaderboard grid': 'leaderboardSkillsGrid' in content,
    }
    for name, ok in required.items():
        assert ok, f'app.html missing required element: {name}'


def test_frontend_asset_integrity():
    assets = ['UI/static/app.css', 'UI/static/app.js', 'UI/templates/app.html']
    for rel in assets:
        path = BASE_DIR / rel
        assert path.exists(), f'Missing {rel}'
        size = path.stat().st_size
        assert size > 1000, f'{rel} is too small: {size} bytes'


def test_frontend_asset_no_orphaned_modals():
    js = JS_PATH.read_text(encoding='utf-8')
    html = HTML_PATH.read_text(encoding='utf-8')
    modals = set(re.findall(r"getElementById('([^']+)')", js))
    modals = {m for m in modals if 'Modal' in m}
    missing = [m for m in modals if m not in html]
    assert not missing, f'JS references undefined modal IDs: {missing}'

