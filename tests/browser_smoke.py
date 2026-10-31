"""Optional Playwright smoke; needs playwright and Chromium, no external bot access."""

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
        while not stop.wait(0.1):
            store.demo_tick()

    worker = threading.Thread(target=tick)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_PATH", "/usr/bin/chromium"),
                headless=True,
                args=["--no-sandbox"],
            )
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#admin").fill(token)
            page.locator("#create").click()
            expect(page.locator("#status")).to_contain_text("已连接")
            page.locator("#body").fill(
                "如何把开源 bot 群聊项目拆成可验收的小步骤？<script>window.pwned=true</script>"
            )
            page.locator("button[type=submit]").click()
            expect(page.locator("#status")).to_contain_text("completed")
            assert page.locator("article").count() == 5
            assert page.evaluate("window.pwned") is None
            assert not errors, errors
            # No credentials in screenshots.
            page.locator("#token").fill("")
            page.locator("#room").fill("")
            Path("artifacts").mkdir(exist_ok=True)
            page.screenshot(path="artifacts/desktop.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path="artifacts/mobile.png", full_page=True)
            browser.close()
        print(
            "Browser smoke passed: create room, 4 replies, completed, XSS inert, mobile layout, no JS errors"
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
