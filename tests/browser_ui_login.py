"""Real browser login-code and remembered-room tests, synthetic local identities only."""

import http.client
import json
import os
import secrets
import threading

from playwright.sync_api import expect, sync_playwright
from roundtable import Store
from server import make_server


def main():
    store = Store()
    store.register_bot("test-worker", "Worker", "dot")
    first = store.create_group("First synthetic room", ["test-worker"])
    second = store.create_group("Last synthetic room", ["test-worker"])
    admin = secrets.token_urlsafe(48)
    server = make_server(store, admin, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"

    def issue():
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        try:
            conn.request(
                "POST",
                "/api/ui-login/issue",
                "{}",
                {"Authorization": "Bearer " + admin, "Content-Type": "application/json"},
            )
            response = conn.getresponse()
            assert response.status == 201
            return json.loads(response.read())["code"]
        finally:
            conn.close()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
            context = browser.new_context(locale="en-US")
            page = context.new_page()
            code = issue()
            page.goto(url + "/#roundtable-login=" + code)
            expect(page.locator("#room-subtitle")).to_contain_text(second["name"])
            assert page.url == url + "/"
            cookies = context.cookies()
            session = next(c for c in cookies if c["name"] == "roundtable_ui")
            assert session["httpOnly"] and session["sameSite"] == "Strict"
            assert "roundtable_ui" not in page.evaluate("document.cookie")
            for kind in ("localStorage", "sessionStorage"):
                assert page.evaluate(f"{kind}.getItem('roundtable-access-v1') === null")
            page.locator(".workspace-picker summary").click()
            page.locator(f'[data-room-id="{first["id"]}"]').click()
            page.reload()
            expect(page.locator("#room-subtitle")).to_contain_text(first["name"])
            page.locator("#access").click()
            expect(page.locator("#remember-access")).to_be_disabled()
            with page.expect_response("**/api/ui-login/revoke") as revoke:
                page.locator("#forget-access").click()
            assert revoke.value.status == 200
            page.reload()
            expect(page.locator("#room-title")).to_have_text("Your roundtable")
            page.goto(url + "/#roundtable-login=" + code)
            expect(page.locator("#error")).not_to_be_empty()
            browser.close()
        print("UI cookie browser: synthetic exchange, privacy, restore, revoke, replay passed")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
