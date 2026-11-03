"""Synthetic group-chat task replies, distinct filters and persistence."""

import os
import re
import secrets
import threading

from playwright.sync_api import expect, sync_playwright

from roundtable import Store
from server import make_server


def main():
    store = Store()
    for bot in ("atlas", "nova", "sage"):
        store.register_bot(bot, bot.title(), "mailbox")
    room = store.create_group("Synthetic chat", ["atlas", "nova", "sage"])
    other = store.create_group("Another synthetic chat", ["atlas", "nova", "sage"])
    topic = store.mailboxes.roundtable(room["id"])["id"]
    for sender, body, mentions in (
        ("bot:atlas", "Atlas message mentioning @nova", ["bot:nova"]),
        ("bot:nova", "Nova independent message", []),
        ("bot:sage", "Sage independent message", []),
    ):
        store.mailboxes.post(
            room["id"],
            sender,
            topic,
            {"body": body, "mentions": mentions, "request_id": secrets.token_hex(12)},
        )

    def create(worker):
        task = store.handoffs.create(
            room["id"],
            "bot:atlas",
            {
                "title": worker.title() + " task",
                "context": "Check the shared chat",
                "assignments": [{"worker": worker, "instruction": "Review " + worker + " layout"}],
                "budget": 4,
                "request_id": secrets.token_hex(12),
            },
        )["task_id"]
        item = store.handoffs.snapshot(room["id"], "user", task)["assignments"][0]
        claim = store.handoffs.operate(
            room["id"],
            "bot:" + worker,
            "claim",
            {
                "task_id": task,
                "assignment_id": item["id"],
                "expected_attempt": 0,
                "request_id": secrets.token_hex(12),
            },
        )
        return task, item, claim

    nova = create("nova")
    sage = create("sage")

    def report(worker, task, kind, body):
        tid, item, claim = task
        store.handoffs.operate(
            room["id"],
            "bot:" + worker,
            "update",
            {
                "task_id": tid,
                "assignment_id": item["id"],
                "lease": claim["lease"],
                "attempt": claim["attempt"],
                "kind": kind,
                "body": body,
                "request_id": secrets.token_hex(12),
            },
        )

    report("nova", nova, "progress", "Nova progress <img src=x onerror=window.chatPwned=1>")
    report("sage", sage, "completed", "Sage finished checking")
    admin = secrets.token_urlsafe(48)
    server = make_server(store, admin, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")

            def connect():
                page.evaluate("token => { adminToken=token;return reloadWorkspace(); }", admin)
                page.evaluate("room => selectRoom(room)", room)

            connect()
            expect(page.locator(".mailbox-message")).to_have_count(3)
            expect(page.locator(".task-message")).to_have_count(2)
            expect(page.locator(".task-reply")).to_have_count(4)
            expect(page.locator(".task-reply").filter(has_text="picked up Atlas")).to_have_count(2)
            expect(page.locator(".task-reply").filter(has_text="Review nova layout")).to_have_count(
                1
            )
            assert page.evaluate("window.chatPwned") is None
            expect(page.locator(".task-reply img")).to_have_count(0)
            # Task cards are embedded in an attributed chat bubble.
            expect(page.locator(".task-message .message-meta strong").first).to_have_text("Atlas")
            expect(page.locator(".task-message .message-content .task-card")).to_have_count(2)
            page.locator("#bot-filter").select_option("bot:nova")
            expect(page.locator(".mailbox-message:visible")).to_have_count(1)
            expect(page.locator(".mailbox-message:visible")).to_contain_text("Nova independent")
            expect(page.locator(".task-message:visible")).to_have_count(1)
            expect(page.locator(".task-message:visible")).to_contain_text("Nova task")
            expect(page.locator(".task-reply:visible")).to_have_count(2)
            page.wait_for_timeout(400)
            page.evaluate("""() => {
                window.idleChanges=0;window.idleAnimations=0;
                new MutationObserver(rows => window.idleChanges+=rows.length)
                    .observe(document.querySelector('#messages'), {childList:true});
                document.querySelector('#messages').addEventListener('animationstart',
                    () => window.idleAnimations++);
            }""")
            page.wait_for_timeout(4100)
            assert page.evaluate("window.idleChanges") == 0
            assert page.evaluate("window.idleAnimations") == 0
            expect(page.locator("#bot-filter")).to_have_value("bot:nova")
            expect(page.locator(".mailbox-message:visible")).to_have_count(1)
            # A live task report joins the same timeline, without replacing its card.
            page.evaluate("window.keptCard=document.querySelector('.task-card')")
            report("nova", nova, "completed", "Nova final result")
            expect(
                page.locator(".task-reply:visible").filter(has_text="Nova final result")
            ).to_have_count(1)
            assert page.evaluate("window.keptCard===document.querySelector('.task-card')")
            page.locator("#task-filter").click()
            expect(page.locator(".mailbox-message:visible")).to_have_count(0)
            expect(page.locator(".task-reply:visible")).to_have_count(3)
            # Reload restores both filters after re-establishing this synthetic login.
            page.reload()
            connect()
            expect(page.locator("#bot-filter")).to_have_value("bot:nova")
            expect(page.locator("#task-filter")).to_have_attribute("aria-pressed", "true")
            expect(page.locator(".mailbox-message:visible")).to_have_count(0)
            expect(page.locator(".task-reply:visible")).to_have_count(3)
            page.evaluate("room => selectRoom(room)", other)
            expect(page.locator("#bot-filter")).to_have_value("")
            expect(page.locator("#task-filter")).to_have_attribute("aria-pressed", "false")
            page.evaluate("room => selectRoom(room)", room)
            expect(page.locator("#bot-filter")).to_have_value("bot:nova")
            expect(page.locator("#task-filter")).to_have_attribute("aria-pressed", "true")
            page.locator("#bot-filter").select_option("bot:sage")
            expect(page.locator(".task-message:visible")).to_contain_text("Sage task")
            expect(page.locator(".task-reply:visible")).to_have_count(2)
            page.locator("#bot-filter").select_option("")
            expect(page.locator(".task-message:visible")).to_have_count(2)
            expect(page.locator(".task-reply:visible")).to_have_count(5)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            toolbar = page.locator(".timeline-toolbar").bounding_box()
            select = page.locator("#bot-filter").bounding_box()
            tasks = page.locator("#task-filter").bounding_box()
            assert toolbar and select and tasks and abs(select["y"] - tasks["y"]) < 5
            expect(page.locator("#body")).to_be_visible()
            # Reading older content does not jump; a reader near the end follows new messages.
            page.locator("#task-filter").click()
            for index in range(30):
                store.mailboxes.post(
                    room["id"],
                    "user",
                    topic,
                    {
                        "body": "Synthetic scroll message " + str(index),
                        "mentions": [],
                        "request_id": "scroll-" + str(index),
                    },
                )
            expect(page.locator(".mailbox-message")).to_have_count(33)
            page.locator("#chat").evaluate("n => n.scrollTop=0")
            store.mailboxes.post(
                room["id"],
                "user",
                topic,
                {
                    "body": "Keep reading earlier messages",
                    "mentions": [],
                    "request_id": "scroll-stay",
                },
            )
            expect(page.locator(".mailbox-message")).to_have_count(34)
            assert page.locator("#chat").evaluate("n => n.scrollTop") == 0
            page.locator("#chat").evaluate("n => n.scrollTop=n.scrollHeight")
            store.mailboxes.post(
                room["id"],
                "user",
                topic,
                {"body": "Follow this new reply", "mentions": [], "request_id": "scroll-follow"},
            )
            expect(page.locator(".mailbox-message")).to_have_count(35)
            page.wait_for_function(
                "document.querySelector('#chat').scrollHeight-document.querySelector('#chat').scrollTop-document.querySelector('#chat').clientHeight < 5"
            )
            # Locale and roster changes update history in place, without replaying arrivals.
            page.wait_for_timeout(400)
            page.evaluate("""() => {
                window.historyNodes=[...document.querySelector('#messages').children];
                window.idleAnimations=0;
                language='zh';translate();
            }""")
            expect(page.locator(".task-reply").filter(has_text="收到 Atlas")).to_have_count(2)
            expect(page.locator(".task-reply-label").first).to_contain_text("任务：")
            store.manage_bot(
                room["id"], "update", {"name": "Atlas renamed", "avatar": "rose"}, "atlas"
            )
            page.evaluate("async () => {await refresh(true);await MailboxUI.refresh();}")
            expect(page.locator(".task-message .message-meta strong").first).to_have_text(
                "Atlas renamed"
            )
            expect(page.locator(".mailbox-message .message-meta strong").first).to_have_text(
                "Atlas renamed"
            )
            expect(page.locator(".task-message .avatar").first).to_have_class(
                re.compile("avatar-rose")
            )
            store.manage_bot(room["id"], "delete", {"confirm": "Nova"}, "nova")
            page.evaluate("async () => {await refresh(true);await MailboxUI.refresh();}")
            expect(page.locator(".mailbox-message .message-meta strong").nth(1)).to_have_text(
                "已删除的 Bot"
            )
            expect(
                page.locator(".task-reply .message-meta strong").filter(has_text="已删除的 Bot")
            ).to_have_count(3)
            expect(page.locator(".task-card .handoff-mini").first).to_have_text("已删除的 Bot")
            assert page.evaluate(
                "window.historyNodes.every(n => n.isConnected && n.parentElement===document.querySelector('#messages'))"
            )
            assert page.evaluate("window.idleAnimations") == 0
            assert not errors, errors
            browser.close()
        print(
            "Chat timeline passed: task replies, sender-only filters, poll/reload/room persistence, mobile"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
