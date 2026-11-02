"""Real browser, synthetic port-zero server; no OS keychain/clipboard/vendor calls."""

import os
import secrets
import threading

from playwright.sync_api import expect, sync_playwright
from handoffs import Handoffs
from roundtable import Store
from server import make_server


def main():
    store = Store()
    token = secrets.token_urlsafe(40)
    store.register_bot("test-origin", "Origin", "grok")
    store.register_bot("test-worker", "Worker", "dot")
    room = store.create_group("Synthetic task room", ["test-origin", "test-worker"])
    Handoffs(store).create(
        room["id"],
        "user",
        {
            "title": "Synthetic task",
            "context": "Read-only test",
            "assignments": [{"worker": "test-worker", "instruction": "Report only"}],
            "budget": 1,
            "timeout_seconds": 600,
            "request_id": "onboarding-test",
        },
    )
    server = make_server(store, token, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    checks = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_PATH") or None, headless=True
            )
            page = browser.new_page(locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            url = f"http://127.0.0.1:{server.server_port}"
            page.goto(url)
            page.locator("#access").click()
            expect(page.locator("#remember-access")).not_to_be_checked()
            page.locator("#admin").fill(token)
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#room-subtitle")).to_contain_text("Synthetic task room")
            page.locator("#task-view").click()
            expect(page.locator("#handoffs-view")).to_be_visible()
            assert page.evaluate("sessionStorage.getItem('roundtable-access-v1') === null")
            assert page.evaluate("localStorage.getItem('roundtable-access-v1') === null")
            page.reload()
            expect(page.locator("#room-title")).to_have_text("Your roundtable")
            page.locator("#access").click()
            page.locator("#admin").fill(token)
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#room-subtitle")).to_contain_text("Synthetic task room")
            page.locator("#discussion-view").click()
            expect(page.locator("#handoffs-view")).not_to_be_visible()
            page.locator("#access").click()
            expect(page.locator("#remember-access")).to_be_disabled()
            checks += 1
            page.locator("#forget-access").click()
            expect(page.locator("#room-title")).to_have_text("Your roundtable")
            for _ in range(2):
                page.locator("#access").click()
                page.locator("#forget-access").click()
            assert page.evaluate(
                "localStorage.getItem('roundtable-access-v1') === null && sessionStorage.getItem('roundtable-access-v1') === null"
            )
            page.reload()
            expect(page.locator("#room-title")).to_have_text("Your roundtable")
            checks += 1
            # Room credentials stay in memory and never recover owner scope.
            page.locator("#access").click()
            page.locator("#room").fill(room["id"])
            page.locator("#token").fill(room["token"])
            page.locator("#room-connect").click()
            expect(page.locator("#room-subtitle")).to_contain_text("Synthetic task room")
            page.reload()
            expect(page.locator("#access")).to_have_text("Connect")
            checks += 1
            # Revocation/invalid saved credential drops browser state.
            page.evaluate(
                "sessionStorage.setItem('roundtable-access-v1', JSON.stringify({admin:'invalid',rooms:[]}))"
            )
            page.reload()
            expect(page.locator("#room-title")).to_have_text("Your roundtable")
            page.wait_for_function("sessionStorage.getItem('roundtable-access-v1') === null")
            checks += 1
            # Storage denial does not prevent an in-memory connection.
            blocked = browser.new_context(locale="en-US")
            blocked.add_init_script(
                "Storage.prototype.getItem=()=>{throw new Error('denied')};Storage.prototype.setItem=()=>{throw new Error('denied')};Storage.prototype.removeItem=()=>{throw new Error('denied')};"
            )
            view = blocked.new_page()
            view.goto(url)
            view.locator("#access").click()
            view.locator("#admin").fill(token)
            view.locator("#access-form button[type=submit]").click()
            expect(view.locator("#room-subtitle")).to_contain_text("Synthetic task room")
            blocked.close()
            checks += 1
            # Even another loopback hostname never persists access tokens.
            other = browser.new_context(locale="en-US")
            host_page = other.new_page()
            host_page.goto(f"http://localhost:{server.server_port}")
            host_page.locator("#access").click()
            expect(host_page.locator("#remember-access")).to_be_disabled()
            host_page.locator("#admin").fill(token)
            host_page.locator("#access-form button[type=submit]").click()
            expect(host_page.locator("#room-subtitle")).to_contain_text("Synthetic task room")
            assert host_page.evaluate(
                "localStorage.getItem('roundtable-access-v1') === null && sessionStorage.getItem('roundtable-access-v1') === null"
            )
            other.close()
            checks += 1
            # Forget invalidates already pending authentication responses.
            page.locator("#access").click()
            page.route(
                "**/api/bots",
                lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
            )
            page.locator("#admin").fill(token)
            page.evaluate(
                "document.querySelector('#access-form').requestSubmit();document.querySelector('#forget-access').click()"
            )
            page.wait_for_timeout(700)
            expect(page.locator("#room-title")).to_have_text("Your roundtable")
            assert page.evaluate("sessionStorage.getItem('roundtable-access-v1') === null")
            assert not errors, errors
            checks += 1
            browser.close()
        print(f"Onboarding browser: {checks} scenarios passed; synthetic identities only")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
