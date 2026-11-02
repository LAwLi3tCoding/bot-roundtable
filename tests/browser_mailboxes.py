"""Real desktop mailbox flows on a synthetic in-memory server with an ephemeral port."""

import http.client
import json
import os
import re
from pathlib import Path
import secrets
import threading

from playwright.sync_api import expect, sync_playwright

from roundtable import Store
from server import make_server


def main():
    store = Store()
    for name, label in (("atlas", "Atlas"), ("nova", "Nova"), ("sage", "Sage")):
        store.register_bot(name, label, "mailbox")
    room = store.create_group("Design studio", ["atlas", "nova", "sage"])
    rid = room["id"]
    store.grant(rid, "atlas", 20)
    store.grant(rid, "nova", 20)
    admin = secrets.token_urlsafe(48)
    server = make_server(store, admin, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"

    def call(path, body=None, token=admin):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
        try:
            connection.request(
                "GET" if body is None else "POST",
                path,
                None if body is None else json.dumps(body),
                {
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                    "Origin": origin,
                },
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    try:
        private = store.mailboxes.create(
            rid,
            "bot:atlas",
            {"members": ["bot:nova"], "title": "Launch notes", "request_id": "seed-topic"},
        )
        store.mailboxes.post(
            rid,
            "bot:atlas",
            private["id"],
            {
                "body": "The first draft is ready. Can you review the conversation flow?",
                "mentions": ["bot:nova"],
                "request_id": "seed-message",
            },
        )
        store.mailboxes.post(
            rid,
            "bot:nova",
            private["id"],
            {
                "body": "I will check the empty states and keep the next steps concise.",
                "request_id": "seed-reply",
            },
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_PATH") or None
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000}, locale="en-US", timezone_id="UTC"
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            status, issued = call("/api/ui-login/issue", {})
            assert status == 201
            page.goto(origin + "/#roundtable-login=" + issued["code"])
            expect(page.locator("#mailbox-list")).to_be_visible()
            expect(page.locator("#room-title")).to_have_text("All")
            page.locator("#mailbox-theme").select_option("light")
            assert page.locator("#sidebar").bounding_box()["width"] == 280
            page.locator("#mailbox-collapse").click()
            assert page.locator("#sidebar").bounding_box()["width"] == 88
            page.locator("#mailbox-collapse").click()
            page.locator("#mailbox-resize").focus()
            expect(page.locator("#mailbox-resize")).to_be_focused()
            page.keyboard.press("End")
            page.keyboard.press("ArrowRight")
            assert page.locator("#sidebar").bounding_box()["width"] == 400
            page.keyboard.press("Home")
            page.keyboard.press("ArrowLeft")
            assert page.locator("#sidebar").bounding_box()["width"] == 240
            page.keyboard.press("ArrowRight")
            assert page.locator("#sidebar").bounding_box()["width"] == 250
            for _ in range(3):
                page.keyboard.press("ArrowRight")
            assert page.locator("#sidebar").bounding_box()["width"] == 280

            page.locator('[data-bot-id="sage"]').click()
            expect(page.locator("#room-title")).to_have_text("Sage")
            assert page.locator("#compose").bounding_box()["height"] == 44
            page.locator("#body").fill("first line\nsecond line")
            expect(page.locator("#compose")).to_have_class(re.compile("composer-expanded"))
            page.locator("#body").fill("short")
            assert "composer-expanded" in page.locator("#compose").get_attribute("class")
            page.locator("#body").fill("")
            assert "composer-expanded" not in page.locator("#compose").get_attribute("class")
            assert page.locator("#compose").bounding_box()["height"] == 44
            # Observe the real insertion animation, including progress across frames.
            page.evaluate("""() => {
                window.motionEvidence = [];
                new MutationObserver(() => {
                    for (const el of document.querySelectorAll('.mailbox-message')) {
                        for (const animation of el.getAnimations()) {
                            if (animation.playState !== 'running') continue;
                            const evidence = {name: animation.animationName, before: animation.currentTime};
                            window.motionEvidence.push(evidence);
                            requestAnimationFrame(() => requestAnimationFrame(() => {
                                evidence.after = animation.currentTime;
                            }));
                        }
                    }
                }).observe(document.querySelector('#messages'), {childList: true, subtree: true});
            }""")
            page.locator("#body").fill("@sage Please outline the review checklist.")
            page.locator("#send").dblclick()
            expect(page.locator(".mailbox-message")).to_have_count(1)
            expect(page.locator(".message-meta strong")).to_have_text("You")
            direct = next(
                t
                for t in store.mailboxes.topics(rid, "user")
                if t["members"] == ["bot:sage", "user"]
            )
            assert len(store.mailboxes.messages(rid, "user", direct["id"])["messages"]) == 1
            assert store.mailboxes.inbox(rid, "user")["messages"] == []
            store.mailboxes.post(
                rid,
                "bot:sage",
                direct["id"],
                {
                    "body": "Start with keyboard navigation, clear labels, and predictable focus.",
                    "request_id": "sage-response",
                },
            )
            expect(page.locator(".mailbox-message")).to_have_count(2)
            expect(page.locator(".message-meta strong").last).to_have_text("Sage")
            expect(page.locator(".mailbox-time-divider")).to_have_count(1)
            page.locator(".mailbox-message").last.focus()
            expect(page.locator(".mailbox-message").last).to_be_focused()
            expect(page.locator(".message-meta time").last).to_have_css("opacity", "1")
            assert all(t["unread"] == 0 for t in store.mailboxes.topics(rid, "user"))
            page.wait_for_function("() => motionEvidence.some(e => e.after > e.before)")
            assert page.locator(".character-eyes").first.evaluate(
                "e => e.getAnimations().some(a => a.playState === 'running')"
            )
            page.locator("#options-open").click()
            page.locator("#mailbox-details-members .member").filter(has_text="Sage").locator(
                "button"
            ).click()
            page.locator("#mailbox-avatar-initial").fill("SG")
            page.locator("#mailbox-avatar-color").select_option("rose")
            page.locator("#mailbox-avatar-character").select_option("initials")
            page.locator('#mailbox-avatar-form button[type="submit"]').click()
            page.keyboard.press("Escape")
            expect(page.locator(".mailbox-message .avatar-rose").last).to_have_text("SG")

            screenshots = Path(os.environ.get("MAILBOX_SCREENSHOTS", "artifacts/mailboxes"))
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=str(screenshots / "mailbox-direct-light.png"),
                full_page=True,
                animations="disabled",
            )
            page.reload()
            page.wait_for_timeout(300)
            assert not errors, errors
            expect(page.locator("#room-title")).to_have_text("Sage")
            expect(page.locator(".mailbox-message")).to_have_count(2)
            expect(page.locator(".mailbox-message .avatar-rose").last).to_have_text("SG")
            page.locator("#mailbox-new").click()
            page.locator('#mailbox-members input[value="bot:atlas"]').check()
            page.locator('#mailbox-members input[value="bot:nova"]').check()
            page.locator("#mailbox-title").fill("Design review")
            page.keyboard.press("Escape")
            expect(page.locator("#mailbox-dialog")).not_to_be_visible()
            assert len(store.mailboxes.topics(rid, "user")) == 2
            page.locator("#mailbox-new").click()
            page.locator('#mailbox-members input[value="bot:atlas"]').check()
            page.locator('#mailbox-members input[value="bot:nova"]').check()
            page.locator("#mailbox-title").fill("Design review")
            page.locator("#mailbox-create-submit").dblclick()
            expect(page.locator("#room-title")).to_have_text("Design review")
            assert len(store.mailboxes.topics(rid, "user")) == 3
            page.locator("#body").fill("@atlas @nova Let us review the first release together.")
            page.locator("#send").click()
            expect(page.locator(".mailbox-message")).to_have_count(1)
            group = next(
                t for t in store.mailboxes.topics(rid, "user") if t["title"] == "Design review"
            )
            store.mailboxes.post(
                rid,
                "bot:atlas",
                group["id"],
                {
                    "body": "The layout is ready. I will focus on the conversation list.",
                    "request_id": "atlas-group",
                },
            )
            store.mailboxes.post(
                rid,
                "bot:nova",
                group["id"],
                {
                    "body": "I will check the composer and keyboard interactions.",
                    "request_id": "nova-group",
                },
            )
            expect(page.locator(".mailbox-message")).to_have_count(3)
            page.screenshot(
                path=str(screenshots / "mailbox-group-light.png"),
                full_page=True,
                animations="disabled",
            )
            page.locator("#body").fill(
                "Review checklist\nKeyboard access, timestamps, and readable messages."
            )
            expect(page.locator("#compose")).to_have_class(re.compile("composer-expanded"))
            page.screenshot(
                path=str(screenshots / "mailbox-composer-light.png"),
                full_page=True,
                animations="disabled",
            )
            page.locator("#body").fill("")
            page.locator("#mailbox-theme").select_option("dark")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            page.screenshot(
                path=str(screenshots / "mailbox-group-dark.png"),
                full_page=True,
                animations="disabled",
            )
            page.locator("#mailbox-all").click()
            expect(page.locator("#room-title")).to_have_text("All")
            expect(page.locator("#composer-wrap")).not_to_be_visible()
            page.screenshot(
                path=str(screenshots / "mailbox-all-dark.png"),
                full_page=True,
                animations="disabled",
            )
            page.locator('#messages [data-topic-id="' + private["id"] + '"]').click()
            expect(page.locator("#mailbox-join")).to_be_visible()
            expect(page.locator(".mailbox-message")).to_have_count(2)
            page.locator("#body").fill("Thanks, both. Please include the accessibility findings.")
            page.locator("#send").click()
            expect(page.locator(".mailbox-message")).to_have_count(3)
            expect(page.locator("#mailbox-join")).not_to_be_visible()
            joined = next(
                t for t in store.mailboxes.topics(rid, "user") if t["id"] == private["id"]
            )
            assert "user" in joined["members"]
            last = store.mailboxes.messages(rid, "user", private["id"])["messages"][-1]
            assert last["recipients"] == ["bot:atlas", "bot:nova"]
            sage_token = next(a["token"] for a in room["agent_tokens"] if a["id"] == "sage")
            status, _ = call(
                f"/api/rooms/{rid}/agents/sage/peer/topics/query",
                {"topic_id": private["id"]},
                sage_token,
            )
            assert status == 404
            status, _ = call(
                f"/api/rooms/{rid}/topics/messages",
                {
                    "topic_id": direct["id"],
                    "body": "forged",
                    "request_id": "forged",
                    "sender": "bot:atlas",
                },
            )
            assert status == 400
            # Fixed midday UTC fixture: adjacent gaps 899s / 900s, then date change.
            ids = [
                m["id"] for m in store.mailboxes.messages(rid, "user", private["id"])["messages"]
            ]
            for message_id, stamp in zip(ids, (1767355200, 1767356099, 1767356999)):
                store.db.execute(
                    "UPDATE mail_messages SET created=? WHERE id=?", (stamp, message_id)
                )
            store.db.commit()
            page.reload()
            expect(page.locator(".mailbox-time-divider")).to_have_count(2)
            store.db.execute("UPDATE mail_messages SET created=? WHERE id=?", (1767398390, ids[1]))
            store.db.execute("UPDATE mail_messages SET created=? WHERE id=?", (1767398410, ids[2]))
            store.db.commit()
            page.reload()
            expect(page.locator(".mailbox-time-divider")).to_have_count(3)
            page.emulate_media(reduced_motion="reduce")
            assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
            assert page.locator(".mailbox-message").first.evaluate(
                "e => parseFloat(getComputedStyle(e).animationDuration) <= .01"
            )
            assert page.locator(".character-eyes").first.evaluate(
                "e => e.getAnimations().length === 0"
            )
            page.set_viewport_size({"width": 600, "height": 850})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            browser.close()
        print("Mailbox browser checks passed")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
