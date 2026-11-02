"""Synthetic browser coverage of structured mention composition."""

import os
import secrets
import threading

from playwright.sync_api import expect, sync_playwright
from roundtable import Store
from server import make_server


def main():
    store = Store()
    store.register_bot("test-worker", "Worker", "dot")
    room = store.create_group("Synthetic mentions", ["test-worker"])
    admin = secrets.token_urlsafe(48)
    server = make_server(store, admin, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
            page = browser.new_page(locale="en-US")
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            expect(page.locator("#hero-create")).to_have_text("Connect workspace")
            expect(page.locator("#room-list")).to_contain_text(
                "Connect to a workspace or room first"
            )
            page.locator("#hero-create").click()
            page.locator("#admin").fill(admin)
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#room-title")).to_have_text(room["name"])
            expect(page.locator(".empty-thread")).to_contain_text("Use Tasks")
            expect(page.locator("#room-subtitle")).to_contain_text("Connection unknown")
            store.connections.probe(room["id"], "test-worker", "synthetic-probe-nonce")
            expect(page.locator("#room-subtitle")).to_contain_text("Connected recently (protocol)")
            with store.transaction():
                store.db.execute("UPDATE connection_probes SET observed=observed-121")
            expect(page.locator("#room-subtitle")).to_contain_text("No recent connection")
            expect(page.locator("#thread-select")).not_to_be_visible()
            expect(page.locator("#room-subtitle")).not_to_contain_text("Lead")
            page.locator("#mcp-open").click()
            expect(page.locator("#mcp-config")).to_contain_text(
                f"http://127.0.0.1:{server.server_port}"
            )
            page.locator("#mcp-dialog .close").click()
            page.locator("#body").fill("@test")
            expect(page.locator("#mention-list")).to_be_visible()
            page.locator("#body").press("ArrowDown")
            page.locator("#body").press("Enter")
            expect(page.locator("#body")).to_have_value("@test-worker ")
            page.locator("#body").fill("@test-worker Please reply")
            with page.expect_request("**/messages") as sent:
                page.locator("#send").click()
            assert sent.value.post_data_json["mentions"] == ["test-worker"]
            expect(page.locator(".message-body").last).to_have_text("@test-worker Please reply")
            expect(page.locator(".message-meta strong").last).to_have_text("Human operator")
            expect(page.locator(".notification-targets").last).to_contain_text("test-worker")
            page.locator(".message-content button").last.click()
            page.locator("#body").fill("Plain reply")
            with page.expect_request("**/messages") as plain:
                page.locator("#send").click()
            assert plain.value.post_data_json["mentions"] == []
            assert isinstance(plain.value.post_data_json["reply_to"], int)
            expect(page.locator(".reply-reference").last).to_be_visible()
            expect(page.locator(".notification-targets").last).to_contain_text("All room bots")
            page.locator("#latest").click()
            assert page.evaluate(
                "document.getElementById('chat').scrollHeight-document.getElementById('chat').scrollTop-document.getElementById('chat').clientHeight < 2"
            )
            expect(page.locator("#stop")).to_be_visible()
            with page.expect_response("**/stop") as stopped:
                page.locator("#stop").click()
            assert stopped.value.status == 200
            expect(page.locator("#stop")).not_to_be_visible()
            store.start(room["id"], "Synthetic timeout", ["test-worker"], 1, "timeout-browser")
            with store.transaction():
                store.db.execute("UPDATE runs SET status='timeout' WHERE room=?", (room["id"],))
            expect(page.locator("#status")).to_contain_text("Replied")
            expect(page.locator("#status")).to_have_attribute(
                "title",
                "No reply arrived before the deadline. Check the bot connection and its event subscription.",
            )
            page.locator("#manage").click()
            expect(page.locator("#member-list")).to_contain_text("No recent connection")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
