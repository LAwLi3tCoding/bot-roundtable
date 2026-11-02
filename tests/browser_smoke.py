"""Owner setup, bilingual mailbox controls and isolation against synthetic HTTP state."""

import os
import secrets
import threading

from playwright.sync_api import expect, sync_playwright

from roundtable import Store
from server import make_server


def main():
    store = Store(demo=True)
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
            page.locator("#access").click()
            page.locator("#admin").fill("wrong-token")
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#access-dialog .dialog-error")).to_have_text(
                "Invalid admin token."
            )
            page.locator("#admin").fill(token)
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#access-dialog")).not_to_be_visible()
            page.locator("#new-room").click()
            page.locator("#name").fill("Product lab")
            page.locator("#create").click()
            expect(page.locator("#secret-dialog")).to_be_visible()
            page.locator("#secret-dialog .close").click()
            expect(page.locator("#secrets")).to_be_empty()
            expect(page.locator("#room-title")).to_have_text("All")
            assert (
                page.locator(".app-shell").evaluate(
                    "n => getComputedStyle(n).gridTemplateColumns.split(' ').length"
                )
                == 2
            )
            page.locator('#mailbox-list [data-bot-id="demo-planner"]').click()
            expect(page.locator("#body")).to_be_visible()
            payload = "Plan safely. <script>window.pwned=true</script>"
            page.locator("#body").fill(payload)
            page.locator("#send").click()
            expect(page.locator(".mailbox-message")).to_have_count(1)
            expect(page.locator(".message-body")).to_have_text(payload)
            assert page.evaluate("window.pwned") is None
            page.locator("#options-open").click()
            expect(page.locator("#mailbox-details")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator("#options-open")).to_be_focused()
            page.locator("#language").select_option("zh")
            expect(page.locator("#manage")).to_have_text("管理")
            expect(page.locator("#mailbox-all")).to_have_text("全部")
            expect(page.locator(".message-meta strong")).to_have_text("你")
            expect(page.locator(".message-body")).to_have_text(payload)
            page.locator("#stop").click()
            expect(page.locator("#status")).to_have_text("已停止回复")
            page.locator("#manage").click()
            page.locator("#edit-name").fill("协作实验室")
            page.locator("#settings-form button[type=submit]").click()
            page.locator("#manage-dialog .close").click()
            # Existing bot management remains functional beside mailbox topics.
            page.locator("#manage").click()
            page.locator("#create-lead").click()
            page.locator("#bot-name").fill("Research Lead")
            page.locator("#bot-id").fill("research-lead")
            page.locator("#bot-kind").select_option("mailbox")
            page.locator("#bot-form button[type=submit]").click()
            expect(page.locator("#secret-dialog")).to_be_visible()
            page.locator("#secret-dialog .close").click()
            expect(page.locator("#lead-select")).to_have_value("research-lead")
            page.locator("#lead-select").select_option("demo-planner")
            page.locator("#settings-form button[type=submit]").click()
            page.locator(".manage-member").filter(has_text="Research Lead").locator(
                ".danger"
            ).click()
            expect(page.locator(".manage-member")).to_have_count(2)
            page.locator("#manage-dialog .close").click()
            page.locator("#mailbox-all").click()
            expect(page.locator("#room-subtitle")).to_contain_text("协作实验室")
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
            page.locator("#manage").click()
            page.locator("#edit-name").fill("Latest room state")
            page.locator("#settings-form button[type=submit]").click()
            expect(page.locator("#room-subtitle")).to_contain_text("Latest room state")
            page.evaluate("window.releaseStale(); window.restoreFetch();")
            page.wait_for_timeout(100)
            expect(page.locator("#room-subtitle")).to_contain_text("Latest room state")
            page.locator("#edit-name").fill("协作实验室")
            page.locator("#settings-form button[type=submit]").click()
            expect(page.locator("#room-subtitle")).to_contain_text("协作实验室")
            page.locator("#manage-dialog .close").click()
            page.locator("#language").select_option("en")
            page.locator("#mcp-open").click()
            expect(page.locator("#mcp-config")).to_contain_text("ROOM_SCOPED_AGENT_TOKEN")
            assert token not in page.locator("#mcp-config").inner_text()
            expect(page.locator("#connection-results")).to_contain_text("No probe observed")
            page.locator("#mcp-dialog .close").click()
            page.locator("#new-room").click()
            page.locator("#name").fill("Separate room")
            page.locator("#create").click()
            page.locator("#secret-dialog .close").click()
            expect(page.locator("article.message")).to_have_count(0)
            expect(page.locator("#messages")).not_to_contain_text(payload)
            page.locator(".workspace-picker summary").click()
            page.locator(".room-nav").filter(has_text="协作实验室").click()
            expect(page.locator("#room-subtitle")).to_contain_text("协作实验室")
            page.locator("#mailbox-list [data-topic-id]").first.click()
            expect(page.locator(".message-body")).to_have_text(payload)
            page.locator("#mailbox-search").click()
            page.locator("#room-search").fill("not a matching conversation")
            expect(page.locator("#mailbox-list .mailbox-row")).to_have_count(0)
            expect(page.locator(".message-body")).to_have_text(payload)
            page.locator("#room-search").fill("")
            page.locator("#mailbox-new").click()
            page.locator("#mailbox-members input").first.check()
            for invalid in ("0", "21", "1.5"):
                page.locator("#mailbox-budget").fill(invalid)
                page.locator("#mailbox-create-submit").click()
                expect(page.locator("#mailbox-dialog")).to_be_visible()
                assert not page.locator("#mailbox-budget").evaluate("n => n.checkValidity()")
            page.keyboard.press("Escape")
            page.locator("#mailbox-theme").select_option("dark")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            missing = page.evaluate(
                "() => [...document.querySelectorAll('[data-i18n],[data-i18n-placeholder],[data-i18n-label]')].flatMap(n => ['en','zh'].filter(l => !I18N[l][n.dataset.i18n || n.dataset.i18nPlaceholder || n.dataset.i18nLabel]))"
            )
            assert missing == [], missing
            page.reload()
            expect(page.locator("#access")).to_have_text("Connect")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            assert not errors, errors
            browser.close()
        print(
            "Browser smoke passed: setup/auth, EN/ZH, mailbox XSS, stop, workspace isolation, search, controls and appearance"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
