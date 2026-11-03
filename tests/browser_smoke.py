"""Bilingual roundtable controls, advanced access and synthetic workspace isolation."""

import os
import secrets
import threading

from playwright.sync_api import expect, sync_playwright

from roundtable import Store
from server import make_server


def main():
    store = Store(demo=True)
    first = store.create_group("Product lab", ["demo-planner", "demo-critic"])
    second = store.create_group("Separate room", ["demo-planner"])
    token = secrets.token_urlsafe(32)
    server = make_server(store, token, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_PATH") or None,
                headless=True,
                args=["--no-sandbox"],
            )
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#login-guide summary").click()
            page.locator("#advanced-access").click()
            page.locator("#admin").fill("wrong-token")
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#access-dialog .dialog-error")).to_have_text(
                "Invalid admin token."
            )
            page.locator("#admin").fill(token)
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#access-dialog")).not_to_be_visible()
            page.evaluate("room => selectRoom(room)", first)
            expect(page.locator("#room-title")).to_have_text("Product lab")
            expect(page.locator("#body")).to_be_visible()
            payload = "Plan safely. <script>window.pwned=true</script>"
            page.locator("#body").fill(payload)
            page.locator("#send").click()
            expect(page.locator(".mailbox-message")).to_have_count(1)
            expect(page.locator(".message-body")).to_have_text(payload)
            assert page.evaluate("window.pwned") is None
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#language").select_option("zh")
            expect(page.locator("#manage")).to_have_text("工作区设置")
            expect(page.locator(".message-meta strong")).to_have_text("你")
            expect(page.locator(".message-body")).to_have_text(payload)
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#manage").click()
            page.locator("#edit-name").fill("协作实验室")
            page.locator("#settings-form button[type=submit]").click()
            page.locator("#manage-dialog .close").click()
            # A held older room poll cannot undo a subsequent owner mutation.
            page.evaluate(r"""() => {
                const original = window.fetch; let held = false;
                window.staleReady = false;
                window.fetch = async (...args) => {
                    const response = await original(...args);
                    if (!held && (!args[1]?.method || args[1].method === 'GET') &&
                        /^\/api\/rooms\/[a-f0-9]{24}$/.test(args[0])) {
                        held = true; window.staleReady = true;
                        await new Promise(resolve => window.releaseStale = resolve);
                    }
                    return response;
                };
                window.restoreFetch = () => { window.fetch = original; };
                void refresh(true);
            }""")
            for _ in range(100):
                if page.evaluate("window.staleReady"):
                    break
                page.wait_for_timeout(20)
            assert page.evaluate("window.staleReady")
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#manage").click()
            page.locator("#edit-name").fill("Latest room state")
            page.locator("#settings-form button[type=submit]").click()
            expect(page.locator("#room-title")).to_contain_text("Latest room state")
            page.evaluate("window.releaseStale(); window.restoreFetch();")
            page.wait_for_timeout(100)
            expect(page.locator("#room-title")).to_contain_text("Latest room state")
            page.locator("#edit-name").fill("协作实验室")
            page.locator("#settings-form button[type=submit]").click()
            expect(page.locator("#room-title")).to_contain_text("协作实验室")
            page.locator("#manage-dialog .close").click()
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#language").select_option("en")
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#mcp-open").click()
            page.locator("#mcp-dialog details > summary").click()
            expect(page.locator("#mcp-config")).to_contain_text("ROOM_SCOPED_AGENT_TOKEN")
            assert token not in page.locator("#mcp-config").inner_text()
            expect(page.locator("#connection-results")).to_contain_text("Not connected yet")
            page.locator("#mcp-dialog .close").click()
            page.evaluate("room => selectRoom(room)", second)
            expect(page.locator("article.message")).to_have_count(0)
            expect(page.locator("#messages")).not_to_contain_text(payload)
            page.evaluate("room => selectRoom(room)", first)
            expect(page.locator(".message-body")).to_have_text(payload)
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#mailbox-theme").select_option("dark")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            missing = page.evaluate(
                "() => [...document.querySelectorAll('[data-i18n],[data-i18n-placeholder],[data-i18n-label]')].flatMap(n => ['en','zh'].filter(l => !I18N[l][n.dataset.i18n || n.dataset.i18nPlaceholder || n.dataset.i18nLabel]))"
            )
            assert missing == [], missing
            page.reload()
            expect(page.locator("#login-guide")).to_be_visible()
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            assert not errors, errors
            browser.close()
        print(
            "Browser smoke passed: auth, EN/ZH, timeline XSS, stale refresh isolation, management, appearance"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
