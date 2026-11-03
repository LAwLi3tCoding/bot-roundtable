"""Shared roundtable behavior and idle DOM stability with synthetic local data."""

import os
import secrets
import threading

from playwright.sync_api import expect, sync_playwright

from roundtable import Store
from server import make_server


def main():
    store = Store()
    for bot in ("grok", "dot", "reviewer"):
        store.register_bot(bot, bot.title(), "mailbox")
    room = store.create_group("Design roundtable", ["grok", "dot", "reviewer"])
    admin = secrets.token_urlsafe(48)
    server = make_server(store, admin, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 960}, locale="zh-CN")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#login-guide summary").click()
            page.locator("#advanced-access").click()
            page.locator("#admin").fill(admin)
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#room-title")).to_have_text("Design roundtable")
            expect(page.locator("#body")).to_be_visible()
            assert page.locator("#sidebar,#mailbox-new,#mailbox-all,#task-view").count() == 0
            topic = page.evaluate("() => state.roundtable.id")
            assert len(store.mailboxes.topics(room["id"], "user")) == 1
            assert set(store.mailboxes.topics(room["id"], "user")[0]["members"]) == {
                "user",
                "bot:grok",
                "bot:dot",
                "bot:reviewer",
            }
            # Plain insertion records context without waking any bot.
            page.locator("#body").fill("先把思路记在这里。")
            expect(page.locator("#notification-preview")).to_contain_text("不会叫醒")
            page.locator("#send").click()
            expect(page.locator(".mailbox-message")).to_have_count(1)
            assert not store.mailboxes.wake_inbox(room["id"], "bot:grok")["messages"]
            assert not store.mailboxes.wake_inbox(room["id"], "bot:dot")["messages"]
            page.locator("#body").fill("@grok 请看这条。")
            expect(page.locator("#notification-preview")).to_have_text("将叫醒：Grok")
            page.locator("#send").click()
            expect(page.locator(".mailbox-message")).to_have_count(2)
            assert len(store.mailboxes.wake_inbox(room["id"], "bot:grok")["messages"]) == 1
            assert not store.mailboxes.wake_inbox(room["id"], "bot:dot")["messages"]
            page.wait_for_timeout(400)
            page.evaluate("""() => {
                window.messageMutations=0;window.messageAnimations=0;
                window.originalMessage=document.querySelector('.mailbox-message');
                new MutationObserver(rows=>window.messageMutations+=rows.filter(r=>r.type==='childList').length)
                  .observe(document.querySelector('#messages'),{childList:true});
                document.querySelector('#messages').addEventListener('animationstart',e=>{
                    if(e.animationName==='message-enter')window.messageAnimations++;
                });
            }""")
            page.wait_for_timeout(6100)
            assert page.evaluate("window.messageMutations") == 0
            assert page.evaluate("window.messageAnimations") == 0
            store.mailboxes.post(
                room["id"],
                "bot:grok",
                topic,
                {
                    "body": "看到了。<img src=x onerror=window.pwned=true>",
                    "mentions": [],
                    "request_id": "browser-reply",
                },
            )
            expect(page.locator(".mailbox-message")).to_have_count(3)
            page.wait_for_timeout(400)
            assert page.evaluate("window.messageAnimations") == 1
            assert page.evaluate(
                "window.originalMessage === document.querySelector('.mailbox-message')"
            )
            assert page.evaluate("window.pwned") is None
            assert page.locator(".message-arriving").count() == 0
            # Filters only change what is shown, never create a private conversation.
            page.locator('[data-bot-filter="bot:grok"]').click()
            expect(page.locator(".mailbox-message:visible")).to_have_count(2)
            page.locator('[data-bot-filter="bot:dot"]').click()
            expect(page.locator(".mailbox-message:visible")).to_have_count(0)
            expect(page.locator(".timeline-empty")).to_be_visible()
            page.locator('[data-bot-filter=""]').click()
            expect(page.locator(".mailbox-message:visible")).to_have_count(3)
            page.locator("#task-filter").click()
            expect(page.locator(".mailbox-message:visible")).to_have_count(0)
            page.locator("#task-filter").click()
            expect(page.locator(".mailbox-message:visible")).to_have_count(3)
            assert len(store.mailboxes.topics(room["id"], "user")) == 1
            # Menu closes on outside click, Esc and selecting a preference.
            menu = page.locator("#mailbox-settings > summary")
            menu.click()
            expect(menu).to_have_attribute("aria-expanded", "true")
            page.locator("#room-title").click()
            expect(menu).to_have_attribute("aria-expanded", "false")
            expect(menu).to_be_focused()
            menu.click()
            page.keyboard.press("Escape")
            expect(menu).to_be_focused()
            menu.click()
            page.locator("#mailbox-theme").select_option("dark")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            assert not page.locator("#mailbox-settings").evaluate("n=>n.open")
            for width in (1024, 720, 390):
                page.set_viewport_size({"width": width, "height": 844})
                expect(page.locator("#body")).to_be_visible()
                expect(page.locator(".mailbox-message").last).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            menu.click()
            panel = page.locator(".sidebar-settings-panel").bounding_box()
            assert panel and panel["x"] >= 0 and panel["x"] + panel["width"] <= 390
            assert not errors, errors
            browser.close()
        print(
            "Roundtable browser: shared timeline, explicit wakes, idle stability, filters, menus, mobile passed"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
