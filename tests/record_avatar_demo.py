"""Record actual browser frames; local synthetic jobs/replies, no provider connection."""

import os
import secrets
import subprocess
import threading
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from roundtable import Store
from server import make_server


def main():
    output = Path("docs/demo")
    output.mkdir(exist_ok=True)
    store = Store()
    room = store.room("头像与状态演示")
    rid = room["id"]
    store.settings(rid, room["name"], "demo-planner")
    store.room("协作实验室")
    token = secrets.token_urlsafe(32)
    server = make_server(store, token, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    encoder = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_PATH") or None,
                headless=True,
                args=["--no-sandbox"],
            )
            page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="zh-CN")
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#access").click()
            page.locator("#admin").fill(token)
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#access-dialog")).not_to_be_visible()
            page.locator(".room-nav").filter(has_text=room["name"]).click()
            page.locator("#options-open").click()
            page.locator("#budget").fill("3")
            page.locator("#options-dialog .close").click()
            encoder = subprocess.Popen(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "image2pipe",
                    "-framerate",
                    "10",
                    "-i",
                    "pipe:0",
                    "-c:v",
                    "libvpx-vp9",
                    "-crf",
                    "36",
                    "-b:v",
                    "0",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    str(output / "avatar-motion.webm"),
                ],
                stdin=subprocess.PIPE,
            )
            frames = 0

            def hold(seconds):
                nonlocal frames
                start = time.monotonic()
                for i in range(int(seconds * 10)):
                    assert token not in page.locator("body").inner_text()
                    encoder.stdin.write(page.screenshot(type="png"))
                    frames += 1
                    remaining = start + (i + 1) / 10 - time.monotonic()
                    if remaining > 0:
                        page.wait_for_timeout(remaining * 1000)

            def reply(agent, body, failed=False):
                jobs = store.inbox(rid, agent)
                assert len(jobs) == 1
                store.reply(rid, agent, jobs[0]["id"], body, failed=failed)
                page.evaluate("refresh(true)")

            def avatar(agent):
                return page.locator(f'#member-list .bot-avatar[data-identity="{agent}"]')

            hold(1)
            page.locator("#body").fill("演示：让两个 demo Bot 在三条回复内协作。")
            page.locator("#send").click()
            expect(page.locator("#status")).to_contain_text("进行中")
            page.locator("#manage").click()
            expect(avatar("demo-planner")).to_have_attribute("data-state", "working")
            hold(4)
            reply("demo-planner", "[DEMO · 测试驱动] 我先规划：确认目标，再检查边界。")
            expect(avatar("demo-critic")).to_have_attribute("data-state", "working")
            hold(2)
            reply("demo-critic", "[DEMO · 测试驱动] 边界检查完成：只处理本群消息，不扩大权限。")
            expect(avatar("demo-planner")).to_have_attribute("data-state", "working")
            hold(2)
            reply("demo-planner", "[DEMO · 测试驱动] 总结：三条回复完成，讨论停止调度。")
            expect(page.locator("#status")).to_contain_text("已完成")
            expect(avatar("demo-planner")).to_have_attribute("data-state", "finished")
            hold(2)
            page.locator("#manage-dialog .close").click()
            hold(2)
            page.screenshot(path="docs/screenshots/desktop-zh.png", full_page=True)
            page.locator("#language").select_option("en")
            page.screenshot(path="docs/screenshots/desktop-en.png", full_page=True)
            hold(1)
            page.locator("#language").select_option("zh")
            page.locator("#body").fill("演示：等待中的任务可以停止。")
            page.locator("#send").click()
            expect(page.locator("#status")).to_contain_text("进行中")
            page.locator("#manage").click()
            expect(avatar("demo-planner")).to_have_attribute("data-state", "working")
            hold(2)
            page.locator("#manage-dialog .close").click()
            page.locator("#stop").click()
            expect(page.locator("#status")).to_contain_text("已停止")
            page.locator("#manage").click()
            expect(avatar("demo-planner")).to_have_attribute("data-state", "idle")
            hold(2)
            page.locator("#manage-dialog .close").click()
            page.locator("#body").fill("演示：测试驱动一次失败回执。")
            page.locator("#send").click()
            expect(page.locator("#status")).to_contain_text("进行中")
            reply("demo-planner", "[DEMO · 测试驱动] 这是一条合成失败回执。", failed=True)
            page.locator("#manage").click()
            expect(avatar("demo-planner")).to_have_attribute("data-state", "blocked")
            hold(3)
            page.screenshot(path="docs/screenshots/desktop-manage-zh.png", full_page=True)
            page.emulate_media(reduced_motion="reduce")
            hold(1)
            encoder.stdin.close()
            assert encoder.wait(timeout=30) == 0
            encoder = None
            browser.close()
            print(
                f"Recorded {frames} actual frames at 10 fps; working/completed/stopped/failed. Synthetic replies only."
            )
    finally:
        if encoder:
            encoder.stdin.close()
            encoder.wait(timeout=30)
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
