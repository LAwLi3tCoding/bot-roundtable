"""Capture five UI variants against a synthetic isolated server.

Usage: python scripts/capture_mailbox_ui.py SOURCE_ROOT OUTPUT_DIRECTORY
"""

import sys
import os
import threading
import secrets
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from roundtable import Store
from server import make_server
from playwright.sync_api import sync_playwright

store = Store()
for bot in ["atlas", "nova", "sage"]:
    store.register_bot(bot, bot.title(), "mailbox")
room = store.create_group("Design studio", ["atlas", "nova", "sage"])
rid = room["id"]
topic = store.mailboxes.roundtable(rid)
seed_messages = [
    (
        "user",
        "我们一起检查新版圆桌。@atlas 先梳理重点，@nova 看一下窄屏。",
        "Let’s review the roundtable. @atlas outline the priorities; @nova check the narrow layout.",
    ),
    (
        "bot:atlas",
        "先确认三件事：消息容易读、任务有进展、需要时能找到每个 Bot。",
        "Three priorities: readable messages, visible task progress, and Bots that are easy to find.",
    ),
    (
        "bot:nova",
        "我来检查 390px 下的时间线和输入框，结果会放在下面的任务里。",
        "I’ll check the timeline and composer at 390px and share the results in the task below.",
    ),
    (
        "bot:sage",
        "深浅主题也一起检查。没有 @ 的这条消息不会通知其他 Bot。",
        "I’ll also review both themes. This message has no mentions, so it won’t notify another Bot.",
    ),
]
for index, (actor, zh, en) in enumerate(seed_messages):
    store.mailboxes.post(
        rid, actor, topic["id"], {"body": zh, "request_id": f"sample-{index}", "mentions": []}
    )
store.handoffs.create(
    rid,
    "user",
    {
        "title": "检查窄屏阅读体验",
        "context": "检查时间线、消息输入和任务详情。",
        "assignments": [
            {"worker": "nova", "instruction": "确认 390px 下没有横向溢出，并记录结果。"}
        ],
        "budget": 6,
        "request_id": "sample-task",
    },
)
admin = secrets.token_urlsafe(48)
server = make_server(store, admin, port=0)
thread = threading.Thread(target=server.serve_forever)
thread.start()
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        for name, lang, theme, width, sidebar in [
            ("desktop-zh-light", "zh", "light", 1440, 300),
            ("desktop-zh-dark", "zh", "dark", 1440, 300),
            ("desktop-en", "en", "light", 1440, 300),
            ("mobile-390", "zh", "light", 390, 300),
            ("settings-420", "zh", "light", 420, 420),
        ]:
            with store.transaction():
                store.db.execute(
                    "UPDATE rooms SET name=? WHERE id=?",
                    ("设计圆桌" if lang == "zh" else "Design roundtable", rid),
                )
                for index, (_, zh, en) in enumerate(seed_messages):
                    store.db.execute(
                        "UPDATE mail_messages SET body=? WHERE request=?",
                        (zh if lang == "zh" else en, f"sample-{index}"),
                    )
                store.db.execute(
                    "UPDATE tasks SET title=?,context=?",
                    (
                        "检查窄屏阅读体验" if lang == "zh" else "Review narrow-screen reading",
                        "检查时间线、消息输入和任务详情。"
                        if lang == "zh"
                        else "Review the timeline, composer and task details.",
                    ),
                )
            context = browser.new_context(
                viewport={"width": width, "height": 900}, locale=lang, timezone_id="UTC"
            )
            page = context.new_page()
            page.add_init_script(
                f"localStorage.setItem('roundtable-language','{lang}');localStorage.setItem('roundtable-theme','{theme}');localStorage.setItem('roundtable-sidebar-width','{sidebar}');"
            )
            # Synthetic instance only; issue session through store's launcher API.
            import urllib.request
            import json

            req = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/ui-login/issue",
                data=b"{}",
                headers={"Authorization": "Bearer " + admin, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as response:
                code = json.load(response)["code"]
            page.goto(f"http://127.0.0.1:{server.server_port}/#roundtable-login={code}")
            page.wait_for_timeout(1000)
            page.locator("#chat").evaluate("node => node.scrollTop = 0")
            if name == "settings-420":
                page.locator("#mailbox-settings > summary").click()
            page.screenshot(path=str(out / (name + ".png")), full_page=True, animations="disabled")
            context.close()
        browser.close()
finally:
    server.shutdown()
    server.server_close()
    thread.join()
