"""Shared roundtable mentions, silent insertion, wake routing and autocomplete."""

import os
import secrets
import threading

from playwright.sync_api import expect, sync_playwright
from roundtable import Store
from server import make_server


def main():
    store = Store()
    for name in ("worker", "reviewer"):
        store.register_bot(name, name.title(), "mailbox")
    room = store.create_group("Synthetic mentions", ["worker", "reviewer"])
    admin = secrets.token_urlsafe(48)
    server = make_server(store, admin, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
            page = browser.new_page(locale="en-US")
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.locator("#login-guide summary").click()
            page.locator("#advanced-access").click()
            page.locator("#admin").fill(admin)
            page.locator("#access-form button[type=submit]").click()
            page.locator("#body").fill("@work")
            expect(page.locator("#mention-list")).to_be_visible()
            expect(page.locator("#mention-list")).not_to_contain_text("Reviewer")
            page.locator("#body").press("ArrowDown")
            page.locator("#body").press("Enter")
            expect(page.locator("#body")).to_have_value("@worker ")
            page.locator("#body").fill("@worker Please reply")
            with page.expect_request("**/topics/messages") as sent:
                page.locator("#send").click()
            assert sent.value.post_data_json["mentions"] == ["bot:worker"]
            expect(page.locator(".message-body").last).to_have_text("@worker Please reply")
            expect(page.locator(".message-meta strong").last).to_have_text("You")
            assert len(store.mailboxes.wake_inbox(room["id"], "bot:worker")["messages"]) == 1
            assert len(store.mailboxes.inbox(room["id"], "bot:reviewer")["messages"]) == 1
            assert store.mailboxes.wake_inbox(room["id"], "bot:reviewer")["messages"] == []
            page.locator("#body").fill("Plain direct message")
            with page.expect_request("**/topics/messages") as plain:
                page.locator("#send").click()
            assert plain.value.post_data_json["mentions"] == []
            expect(page.locator(".message-body")).to_have_count(2)
            page.locator("#body").fill("@nobody This bot is not a member")
            page.locator("#send").click()
            expect(page.locator("#error")).to_contain_text("Check the entered values.")
            expect(page.locator(".message-body")).to_have_count(2)
            expect(page.locator("#body")).to_have_value("@nobody This bot is not a member")
            page.locator("#mailbox-settings > summary").click()
            page.locator("#manage").click()
            page.locator("#manage-dialog details summary").click()
            with page.expect_response("**/topics/stop") as stopped:
                page.locator("#stop").click()
            assert stopped.value.status == 200
            expect(page.locator("#stop")).to_be_disabled()
            assert store.mailboxes.wake_inbox(room["id"], "bot:worker")["messages"] == []
            browser.close()
        print(
            "Roundtable mentions: completion, targeted wake, silent insertion, invalid bot rejection, draft retention, stop passed"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
