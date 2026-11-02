"""Desktop bilingual flows against real local HTTP; deterministic demo bots only."""

import os
import secrets
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from roundtable import Store
from server import make_server


def main():
    store = Store()
    token = secrets.token_urlsafe(32)
    server = make_server(store, token, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    stop = threading.Event()

    def tick():
        while not stop.wait(0.15):
            store.demo_tick()

    worker = threading.Thread(target=tick)
    worker.start()
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
            expect(page.locator(".welcome h2")).to_have_text("Bring your bots to the table.")
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
            expect(page.locator("#room-title")).to_have_text("Product lab")
            # Management is on demand; the resting shell has just list and chat.
            assert (
                page.locator(".app-shell").evaluate(
                    "n => getComputedStyle(n).gridTemplateColumns.split(' ').length"
                )
                == 2
            )
            expect(page.locator("#details")).not_to_be_visible()
            page.locator("#options-open").click()
            expect(page.locator("#options-dialog")).to_be_visible()
            expect(page.locator(".participant-chip")).to_have_count(2)
            first_target = page.locator(".participant-chip").first
            first_target.click()
            expect(first_target).to_have_attribute("aria-pressed", "false")
            first_target.click()
            expect(first_target).to_have_attribute("aria-pressed", "true")
            page.locator("#budget").fill("4")
            page.keyboard.press("Escape")
            expect(page.locator("#options-dialog")).not_to_be_visible()
            page.locator("#options-open").click()
            expect(page.locator("#budget")).to_have_value("4")
            page.locator("#options-dialog .close").click()
            expect(page.locator("#options-open")).to_be_focused()
            page.locator("#manage").click()
            page.locator("#lead-select").select_option("demo-planner")
            page.locator("#settings-form button[type=submit]").click()
            page.locator("#manage-dialog .close").click()
            page.locator("#body").fill(
                "Plan a safe collaboration. <script>window.pwned=true</script>"
            )
            page.locator("#send").click()
            expect(page.locator("#status")).to_contain_text("Completed", timeout=10000)
            expect(page.locator("article.message")).to_have_count(5)
            assert page.evaluate("window.pwned") is None
            expect(page.locator("#messages")).to_contain_text("[DEMO Lead]")
            human = page.locator(".human .message-body").first
            bot = page.locator(".bot .message-body").first
            assert human.evaluate("n => getComputedStyle(n).backgroundColor") == "rgb(17, 17, 17)"
            assert bot.evaluate("n => getComputedStyle(n).backgroundColor") == "rgb(243, 243, 242)"
            assert human.bounding_box()["x"] > bot.bounding_box()["x"]
            original = page.locator("#messages").inner_text()
            page.locator("#language").select_option("zh")
            expect(page.locator("#manage")).to_have_text("管理")
            expect(page.locator("#status")).to_contain_text("已完成")
            expect(page.locator("#body")).to_have_attribute(
                "placeholder", "这次想让大家一起讨论什么？"
            )
            # Message body is not translated when switching the UI language.
            expect(page.locator("#messages")).to_contain_text("Plan a safe collaboration.")
            assert "[DEMO Lead]" in original
            # Register a standalone Lead identity, join it, and exercise waiting/stop.
            page.locator("#manage").click()
            page.locator("#create-lead").click()
            page.locator("#bot-name").fill("Research Lead")
            page.locator("#bot-id").fill("research-lead")
            page.locator("#bot-kind").select_option("mailbox")
            page.locator("#bot-form button[type=submit]").click()
            expect(page.locator("#secret-dialog")).to_be_visible()
            page.locator("#secret-dialog .close").click()
            expect(page.locator("#lead-select")).to_have_value("research-lead")
            page.locator("#manage-dialog .close").click()
            page.locator("#body").fill("Waiting for owner-connected Lead")
            page.locator("#send").click()
            expect(page.locator("#status")).to_contain_text("进行中")
            page.locator("#stop").click()
            expect(page.locator("#status")).to_contain_text("已停止")
            # History is real, stable and room-scoped.
            first_run = store.state(store.list_rooms()[0]["id"])["runs"][0]["id"]
            page.locator("#thread-select").select_option(first_run)
            expect(page.locator("article.message")).to_have_count(5)
            # Remove external Lead and rename room through management.
            page.locator("#manage").click()
            page.locator("#edit-name").fill("协作实验室")
            page.locator("#lead-select").select_option("demo-planner")
            page.locator("#settings-form button[type=submit]").click()
            external_row = page.locator(".manage-member").filter(has_text="Research Lead")
            external_row.locator(".danger").click()
            expect(page.locator(".manage-member")).to_have_count(2)
            page.locator("#manage-dialog .close").click()
            expect(page.locator("#room-title")).to_have_text("协作实验室")
            Path("artifacts").mkdir(exist_ok=True)
            page.screenshot(path="artifacts/desktop-zh.png", full_page=True)
            page.locator("#language").select_option("en")
            page.screenshot(path="artifacts/desktop-en.png", full_page=True)
            page.locator("#mcp-open").click()
            expect(page.locator("#mcp-config")).to_contain_text("ROOM_SCOPED_AGENT_TOKEN")
            assert token not in page.locator("#mcp-config").inner_text()
            expect(page.locator("#connection-results")).to_contain_text("No probe observed")
            with store.lock:
                store.connections.probe(
                    store.list_rooms()[0]["id"], "demo-planner", "browser-probe-nonce"
                )
            page.locator("#connection-refresh").click()
            expect(page.locator("#connection-results")).to_contain_text("Last scoped request")
            expect(page.locator("#connection-results")).to_contain_text("browser-probe-nonce")
            page.locator("#mcp-dialog .close").click()
            page.locator("#language").select_option("zh")
            page.locator("#mcp-open").click()
            expect(page.locator("#connection-check")).to_contain_text("连接证据")
            page.locator("#mcp-dialog .close").click()
            page.locator("#language").select_option("en")
            page.locator("#mcp-open").click()
            page.locator("#mcp-dialog .close").click()
            # Create a second room; no prior discussion is visible.
            page.locator("#new-room").click()
            page.locator("#name").fill("Separate room")
            page.locator("#create").click()
            page.locator("#secret-dialog .close").click()
            expect(page.locator("article.message")).to_have_count(0)
            page.locator(".room-nav").filter(has_text="协作实验室").click()
            page.locator("#thread-select").select_option(first_run)
            expect(page.locator("article.message")).to_have_count(5)
            # All static translation keys exist in both dictionaries.
            missing = page.evaluate(
                "() => [...document.querySelectorAll('[data-i18n],[data-i18n-placeholder],[data-i18n-label]')].flatMap(n => ['en','zh'].filter(l => !I18N[l][n.dataset.i18n || n.dataset.i18nPlaceholder || n.dataset.i18nLabel]))"
            )
            assert missing == [], missing
            assert page.evaluate(
                "Object.keys(I18N.en).sort().join() === Object.keys(I18N.zh).sort().join()"
            )
            # Search does not navigate or discard the current conversation.
            page.locator("#room-search").fill("not a matching room")
            expect(page.locator(".room-nav")).to_have_count(0)
            expect(page.locator("#room-list")).to_have_text("No matching conversations")
            expect(page.locator("#room-title")).to_have_text("协作实验室")
            page.locator("#room-search").fill("Separate")
            expect(page.locator(".room-nav")).to_have_count(1)
            page.locator("#room-search").fill("")
            expect(page.locator(".room-nav")).to_have_count(2)
            page.locator("#manage").click()
            page.keyboard.press("Escape")
            expect(page.locator("#manage-dialog")).not_to_be_visible()
            expect(page.locator("#manage")).to_be_focused()
            # Hold an old poll response while a mutation triggers its own fresh read.
            # The mutation must not skip refresh, and the delayed poll must not overwrite it.
            page.evaluate(r"""() => {
                const original = window.fetch;
                let held = false;
                window.staleReady = false;
                window.fetch = async (...args) => {
                    const response = await original(...args);
                    if (!held && (!args[1]?.method || args[1].method === 'GET') &&
                        /^\/api\/rooms\/[a-f0-9]{24}$/.test(args[0])) {
                        held = true;
                        window.staleReady = true;
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
            expect(page.locator("#room-title")).to_have_text("Latest room state")
            page.evaluate("window.releaseStale(); window.restoreFetch();")
            page.wait_for_timeout(100)
            expect(page.locator("#room-title")).to_have_text("Latest room state")
            page.locator("#edit-name").fill("协作实验室")
            page.locator("#settings-form button[type=submit]").click()
            expect(page.locator("#room-title")).to_have_text("协作实验室")
            page.locator("#manage-dialog .close").click()
            # Invalid values in the detached options dialog must never queue a run.
            before_runs = len(store.state(store.list_rooms()[0]["id"])["runs"])
            page.locator("#body").fill("Budget validation only")
            for invalid in ("0", "21", "1.5"):
                page.locator("#options-open").click()
                page.locator("#budget").fill(invalid)
                page.keyboard.press("Escape")
                page.locator("#send").click()
                expect(page.locator("#options-dialog")).to_be_visible()
                expect(page.locator("#budget")).to_be_focused()
                assert not page.locator("#budget").evaluate("n => n.checkValidity()")
                page.locator("#budget").fill("4")
                page.locator("#options-dialog .close").click()
            assert len(store.state(store.list_rooms()[0]["id"])["runs"]) == before_runs
            page.locator("#body").fill("")
            for _ in range(3):
                page.locator("#manage").click()
                expect(page.locator("#details")).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator("#manage")).to_be_focused()
                page.locator("#mcp-open").click()
                page.locator("#mcp-dialog .close").click()
                expect(page.locator("#mcp-open")).to_be_focused()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#language").select_option("zh")
            # Default access survives refresh in session storage, while only language is persistent.
            page.reload()
            expect(page.locator("#manage")).to_have_text("管理")
            expect(page.locator("#access")).to_have_text("Owner 连接")
            assert page.evaluate("Object.keys(localStorage)") == ["roundtable-language"]
            assert not errors, errors
            browser.close()
        print(
            "Browser product checks passed: EN/ZH, group creation/isolation, Lead, register/remove, history, stop, XSS, desktop layout/search/options, session access and language-only local persistence"
        )
    finally:
        stop.set()
        worker.join()
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
