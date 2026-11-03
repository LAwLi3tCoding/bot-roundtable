"""Local cookie Bot management with synthetic identities and no persisted credentials."""

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
    store.register_bot("atlas", "Atlas", "mailbox")
    store.create_group("Synthetic studio", ["atlas"])
    admin = secrets.token_urlsafe(48)
    server = make_server(store, admin, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    connection.request("POST", "/api/ui-login/issue", "{}", {"Authorization": "Bearer " + admin})
    response = connection.getresponse()
    assert response.status == 201
    code = json.loads(response.read())["code"]
    connection.close()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
            context = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url + "/#roundtable-login=" + code)
            expect(page.locator("#room-title")).to_have_text("Synthetic studio")
            page.locator("#directory").click()
            expect(page.locator("#bot-add")).to_be_visible()
            page.locator("#bot-add").click()
            page.locator("#bot-name").fill("Nova")
            expect(page.locator("#bot-id")).to_have_value("nova")
            page.locator('#bot-avatar-options input[value="rose"]').check()
            page.locator("#bot-wake").select_option("mcp-events")
            page.locator("#bot-save").click()
            expect(page.locator("#bot-token-dialog")).to_be_visible()
            expect(page.locator("#bot-created-token")).not_to_be_empty()
            token = page.locator("#bot-created-token").inner_text()
            expect(page.locator("#bot-created-command")).to_contain_text("connect-bot --bot nova")
            assert token not in page.evaluate("JSON.stringify({...localStorage,...sessionStorage})")
            page.evaluate("window.dispatchEvent(new Event('pagehide'))")
            expect(page.locator("#bot-created-token")).to_be_empty()
            row = page.locator('[data-bot-id="nova"]')
            expect(row).to_be_visible()
            row.get_by_role("button", name="Edit Bot", exact=True).click()
            page.locator("#bot-name").fill("Nova Review")
            page.locator("#bot-limit").fill("7")
            page.locator('#bot-avatar-options input[value="blue"]').check()
            page.locator("#bot-save").click()
            expect(page.locator("#bot-editor-dialog")).not_to_be_visible()
            expect(row).to_contain_text("Nova Review")
            expect(row.locator(".avatar-blue")).to_be_visible()
            page.once("dialog", lambda dialog: dialog.accept())
            row.get_by_role("button", name="Pause Bot", exact=True).click()
            expect(row.get_by_role("button", name="Resume Bot", exact=True)).to_be_visible()
            row.get_by_role("button", name="Resume Bot", exact=True).click()
            expect(row.get_by_role("button", name="Pause Bot", exact=True)).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator("#directory-dialog").evaluate("n => n.scrollWidth <= n.clientWidth")
            row.get_by_role("button", name="Delete Bot", exact=True).click()
            expect(page.locator("#bot-delete-submit")).to_be_disabled()
            page.locator("#bot-delete-confirm").fill("wrong")
            expect(page.locator("#bot-delete-submit")).to_be_disabled()
            page.locator("#bot-delete-confirm").fill("Nova Review")
            page.locator("#bot-delete-submit").click()
            expect(page.locator("#bot-delete-dialog")).not_to_be_visible()
            expect(row).to_contain_text("Deleted Bot")
            expect(row.locator("button")).to_have_count(0)
            page.locator("#directory-dialog .close").click()
            page.reload()
            page.locator("#directory").click()
            expect(page.locator("#bot-created-token")).to_be_empty()
            assert token not in page.locator("body").inner_text()
            # Ending the local login clears a newly displayed token immediately.
            page.locator("#bot-add").click()
            page.locator("#bot-name").fill("Helper")
            page.locator("#bot-save").click()
            expect(page.locator("#bot-token-dialog")).to_be_visible()
            page.evaluate("forgetAccess()")
            expect(page.locator("#bot-created-token")).to_be_empty()
            expect(page.locator("#bot-token-dialog")).not_to_be_visible()
            # A bearer-admin view has no management controls, even on localhost.
            other = browser.new_page()
            other.goto(url)
            other.evaluate("token => {adminToken=token; return reloadWorkspace();}", admin)
            other.evaluate("() => selectRoom(rooms[0])")
            other.locator("#directory").click()
            expect(other.locator("#bot-add")).not_to_be_visible()
            expect(other.locator("#bot-local-only")).to_be_visible()
            expect(other.locator(".bot-row-actions")).to_have_count(0)
            assert not errors, errors
            browser.close()
        print(
            "Bot management browser: local cookie create/edit/pause/resume/delete, one-time token, mobile and bearer denial passed"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
