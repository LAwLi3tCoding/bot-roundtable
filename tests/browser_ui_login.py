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

    count = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_PATH") or None, headless=True
            )
            context = browser.new_context(locale="en-US")
            page = context.new_page()
            page.goto(url)
            page.locator("#access").click()
            page.locator("#remember-access").check()
            page.locator("#admin").fill(admin)
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#room-title")).to_have_text(second["name"])
            page.locator(f'[data-room-id="{first["id"]}"]').click()
            page.reload()
            expect(page.locator("#room-title")).to_have_text(first["name"])
            count += 1
            code = issue()
            cleared = []

            def observe(route):
                cleared.append(page.evaluate('location.hash === ""'))
                route.continue_()

            page.route("**/api/ui-login/exchange", observe)
            page.goto(url + "/#roundtable-login=" + code)
            expect(page.locator("#room-title")).to_have_text(second["name"])
            selfree = page.locator("body").inner_text()
            assert code not in selfree and admin not in selfree
            assert page.url == url + "/" and cleared == [True]
            assert page.evaluate("localStorage.getItem('roundtable-access-v1') === null")
            session = page.evaluate(
                "JSON.parse(sessionStorage.getItem('roundtable-access-v1')).admin"
            )
            assert session != admin
            page.locator("#access").click()
            expect(page.locator("#remember-access")).to_be_disabled()
            page.locator("#access-dialog .close").click()
            page.reload()
            expect(page.locator("#room-title")).to_have_text(second["name"])
            count += 1
            # Reuse is rejected, with no fallback to an old remembered administrator.
            page.goto(url + "/#roundtable-login=" + code)
            expect(page.locator("#room-title")).to_have_text("Your roundtable")
            expect(page.locator("#error")).not_to_be_empty()
            assert page.evaluate('location.hash === ""')
            count += 1
            # Server monotonic expiry, without sleeping a minute.
            codes = getattr(server, "ui_sessions")
            clock = codes.clock
            now = [clock()]
            codes.clock = lambda: now[0]
            expired = issue()
            now[0] += 60
            page.goto(url + "/#roundtable-login=" + expired)
            expect(page.locator("#error")).not_to_be_empty()
            expect(page.locator("#room-title")).to_have_text("Your roundtable")
            codes.clock = clock
            count += 1
            # Browser request with a foreign origin cannot exchange a valid code.
            fresh = issue()
            response = context.request.post(
                url + "/api/ui-login/exchange",
                data={"code": fresh},
                headers={"Origin": "http://example.com"},
            )
            assert response.status == 403
            response = context.request.post(
                url + "/api/ui-login/exchange",
                data={"code": fresh},
                headers={"Origin": url, "Host": f"localhost:{server.server_port}"},
            )
            assert response.status == 403
            page.goto(url + "/#roundtable-login=" + fresh)
            expect(page.locator("#room-title")).to_have_text(second["name"])
            count += 1
            # A manual paste cannot turn a short-lived session into a remembered token.
            session = page.evaluate(
                "JSON.parse(sessionStorage.getItem('roundtable-access-v1')).admin"
            )
            room_page = context.new_page()
            room_page.goto(url)
            room_page.locator("#access").click()
            room_page.locator("#remember-access").check()
            room_page.locator("#room").fill(second["id"])
            room_page.locator("#token").fill(session)
            room_page.locator("#room-connect").click()
            expect(room_page.locator("#room-title")).to_have_text("Your roundtable")
            assert room_page.evaluate("localStorage.getItem('roundtable-access-v1') === null")
            room_page.evaluate(
                "([id, token])=>localStorage.setItem('roundtable-access-v1', JSON.stringify({admin:'',rooms:[[id,token]]}))",
                [second["id"], session],
            )
            room_page.reload()
            expect(room_page.locator("#room-title")).to_have_text("Your roundtable")
            assert room_page.evaluate("localStorage.getItem('roundtable-access-v1') === null")
            room_page.close()
            count += 1
            manual = context.new_page()
            manual.goto(url)
            manual.locator("#access").click()
            manual.locator("#remember-access").check()
            manual.locator("#admin").fill(session)
            manual.locator("#access-form button[type=submit]").click()
            expect(manual.locator("#room-title")).to_have_text(second["name"])
            assert manual.evaluate("localStorage.getItem('roundtable-access-v1') === null")
            manual.locator("#access").click()
            expect(manual.locator("#remember-access")).to_be_disabled()
            manual.locator("#access-dialog .close").click()
            manual.evaluate(
                "localStorage.setItem('roundtable-access-v1',JSON.stringify({admin:JSON.parse(sessionStorage.getItem('roundtable-access-v1')).admin,rooms:[],temporary:false}));sessionStorage.clear()"
            )
            manual.reload()
            expect(manual.locator("#room-title")).to_have_text(second["name"])
            assert manual.evaluate("localStorage.getItem('roundtable-access-v1') === null")
            count += 1
            manual.locator("#access").click()
            manual.locator("#forget-access").click()
            response = context.request.get(
                url + "/api/rooms", headers={"Authorization": "Bearer " + session}
            )
            assert response.status == 403
            count += 1
            held = []
            page.unroute("**/api/ui-login/exchange", observe)
            page.route("**/api/ui-login/exchange", lambda route: held.append(route))
            pending = issue()
            page.goto(url + "/#roundtable-login=" + pending)
            page.wait_for_timeout(150)
            page.locator("#access").click()
            page.locator("#forget-access").click()
            for route in held:
                route.continue_()
            page.wait_for_timeout(300)
            expect(page.locator("#room-title")).to_have_text("Your roundtable")
            assert page.evaluate("sessionStorage.getItem('roundtable-access-v1') === null")
            count += 1
            browser.close()
        print(f"UI login browser: {count} scenarios passed; synthetic credentials only")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
