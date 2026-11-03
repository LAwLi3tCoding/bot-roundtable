"""Real stdio MCP identities and desktop browser sharing one task/event store.

Synthetic mailbox actors only. Set HANDOFF_RECORD=1 to save a real browser video.
"""

import asyncio
import concurrent.futures
import json
import os
from pathlib import Path
import secrets
import sys
import subprocess
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.sync_api import expect, sync_playwright

from roundtable import Store
from server import make_server

ROOT = Path(__file__).resolve().parents[1]


class Clients:
    def __init__(self, url, room, agents):
        self.ready = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=lambda: asyncio.run(self.run(url, room, agents)))
        self.thread.start()
        assert self.ready.wait(30), "MCP startup timed out"
        if self.error:
            raise self.error

    async def run(self, url, room, agents):
        try:
            async with AsyncExitStack() as stack:
                self.loop = asyncio.get_running_loop()
                self.queue = asyncio.Queue()
                sessions = {}
                for agent in agents:
                    env = dict(
                        os.environ,
                        ROUNDTABLE_URL=url,
                        ROUNDTABLE_ROOM=room,
                        ROUNDTABLE_AGENT=agent["id"],
                        ROUNDTABLE_TOKEN=agent["token"],
                    )
                    streams = await stack.enter_async_context(
                        stdio_client(
                            StdioServerParameters(
                                command=sys.executable, args=[str(ROOT / "mcp_bridge.py")], env=env
                            )
                        )
                    )
                    session = await stack.enter_async_context(ClientSession(*streams))
                    await session.initialize()
                    assert "create_task" in {x.name for x in (await session.list_tools()).tools}
                    sessions[agent["id"]] = session
                self.ready.set()
                while (item := await self.queue.get()) is not None:
                    agent, tool, args, future, fail = item
                    try:
                        result = await sessions[agent].call_tool(tool, args)
                        if fail:
                            assert result.isError, "Unauthorized operation unexpectedly succeeded"
                            future.set_result(None)
                        else:
                            assert not result.isError, str(result.content)
                            data = result.structuredContent
                            future.set_result(
                                data.get("result", data)
                                if data is not None
                                else json.loads(result.content[0].text)
                            )
                    except Exception as exc:
                        future.set_exception(exc)
        except Exception as exc:
            self.error = exc
            self.ready.set()

    def call(self, agent, tool, fail=False, **args):
        future = concurrent.futures.Future()
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (agent, tool, args, future, fail))
        return future.result(30)

    def close(self):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)
        self.thread.join(20)
        assert not self.thread.is_alive()
        if self.error:
            raise self.error


def main():
    store = Store(demo=True)
    ids = ["entry-demo", "research-demo", "review-demo"]
    for aid, name in zip(ids, ["Demo Entry", "Demo Research", "Demo Review"]):
        store.register_bot(aid, name, "mailbox", "Synthetic MCP protocol test")
    room = store.create_group("DEMO · Native handoffs", ids)
    other = store.room("DEMO · Web tasks")
    store.grant(room["id"], ids[0], 20)
    store.settings(room["id"], room["name"], ids[0])
    admin = secrets.token_urlsafe(32)
    server = make_server(store, admin, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    clients = Clients(f"http://127.0.0.1:{server.server_port}", room["id"], room["agent_tokens"])
    artifacts = ROOT / "artifacts/handoffs"
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_PATH") or None,
                args=["--no-sandbox"],
            )
            context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#access").click()
            page.locator("#admin").fill(admin)
            page.locator("#access-form button[type=submit]").click()
            expect(page.locator("#access-dialog")).not_to_be_visible()
            page.locator("#mailbox-settings").evaluate("e => e.open = true")
            page.locator(".workspace-picker").evaluate("e => e.open = true")
            page.locator(".room-nav").filter(has_text=room["name"]).click()
            page.locator("#task-view").click()

            def call(tool, **args):
                return clients.call(ids[0], tool, **args)

            def create(title):
                return call(
                    "create_task",
                    title=title,
                    context="DEMO: compare two independent approaches.",
                    assignments=[
                        {"worker": ids[1], "instruction": "Research accessibility requirements."},
                        {
                            "worker": ids[2],
                            "instruction": "Review communication safety boundaries.",
                        },
                    ],
                    request_id=secrets.token_hex(12),
                    budget=6,
                )["task_id"]

            def refresh():
                page.evaluate("() => refresh(true)")

            def report(worker, item, claim, kind, body):
                return clients.call(
                    worker,
                    "report_assignment",
                    task_id=item["task_id"],
                    assignment_id=item["id"],
                    lease=claim["lease"],
                    attempt=claim["attempt"],
                    kind=kind,
                    body=body,
                    request_id=secrets.token_hex(12),
                )

            tid = create("DEMO · Plan a useful collaboration")
            refresh()
            page.locator(f'[data-task-id="{tid}"]').click()
            expect(page.locator("#task-header")).to_contain_text(tid)
            # Task audit remains in the task view; private topics never receive task notices.
            page.locator("#discussion-view").click()
            expect(page.locator("#handoffs-view")).not_to_be_visible()
            expect(page.locator(".message-content")).to_have_count(0)
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#language").select_option("zh")
            page.locator("#task-view").click()
            expect(page.locator("#task-header")).to_contain_text(tid)
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#language").select_option("en")
            inbox = [clients.call(a, "receive_assignments")[0] for a in ids[1:]]
            assert inbox[0]["instruction"] != inbox[1]["instruction"]
            claims = [
                clients.call(
                    a,
                    "claim_assignment",
                    task_id=tid,
                    assignment_id=item["id"],
                    expected_attempt=0,
                    request_id=secrets.token_hex(12),
                )
                for a, item in zip(ids[1:], inbox)
            ]
            clients.call(
                ids[2],
                "claim_assignment",
                fail=True,
                task_id=tid,
                assignment_id=inbox[0]["id"],
                expected_attempt=0,
                request_id="wrong-worker",
            )
            page.locator(f'[data-assignment-id="{inbox[0]["id"]}"]').click()
            expect(page.locator("#handoff-instruction")).to_contain_text(inbox[0]["instruction"])
            report(
                ids[1],
                inbox[0],
                claims[0],
                "progress",
                "DEMO: checking keyboard navigation and contrast.",
            )
            refresh()
            expect(page.locator("#handoff-events")).to_contain_text(
                "checking keyboard navigation", timeout=10000
            )
            page.locator("#task-note").fill(
                "Private research context <img src=x onerror=window.taskPwned=1>"
            )
            page.locator("#task-note-form button[type=submit]").click()
            expect(page.locator("#handoff-events")).to_contain_text("Private research context")
            assert page.evaluate("window.taskPwned") is None
            assert page.locator("#handoff-events img").count() == 0
            a_snapshot = clients.call(ids[1], "get_task", task_id=tid)
            b_snapshot = clients.call(ids[2], "get_task", task_id=tid)
            assert "Private research context" in json.dumps(a_snapshot)
            assert "Private research context" not in json.dumps(b_snapshot)
            report(
                ids[2],
                inbox[1],
                claims[1],
                "failed",
                "DEMO: missing review context; retry requested.",
            )
            refresh()
            page.locator(f'[data-assignment-id="{inbox[1]["id"]}"]').click()
            expect(page.locator("#retry-task")).to_be_visible(timeout=10000)
            page.locator("#retry-task").click()
            expect(page.locator("#retry-task")).not_to_be_visible()
            claims[1] = clients.call(
                ids[2],
                "claim_assignment",
                task_id=tid,
                assignment_id=inbox[1]["id"],
                expected_attempt=1,
                request_id="retry-claim",
            )
            report(
                ids[1],
                inbox[0],
                claims[0],
                "completed",
                "DEMO result: retain keyboard access and readable status text.",
            )
            report(
                ids[2],
                inbox[1],
                claims[1],
                "completed",
                "DEMO result: isolate member scope and keep origin polling explicit.",
            )
            assert call("get_task", task_id=tid)["task"]["status"] == "completed"
            refresh()
            expect(page.locator("#task-header")).to_contain_text("Completed", timeout=10000)
            # Open another task with held query: stale task contents/actions must disappear immediately.
            second = create("DEMO · Cancellation check")
            page.locator("#task-back").click()
            refresh()
            held = []

            def delay_query(route):
                if route.request.post_data_json.get("task_id") == second:
                    held.append(route)
                else:
                    route.continue_()

            page.route("**/tasks/query", delay_query)
            page.locator(f'[data-task-id="{second}"]').click()
            page.wait_for_timeout(200)
            expect(page.locator("#handoff-instruction")).not_to_contain_text(
                inbox[1]["instruction"]
            )
            expect(page.locator("#cancel-task")).to_be_disabled()
            for route in held:
                route.continue_()
            page.unroute("**/tasks/query", delay_query)
            expect(page.locator("#cancel-task")).to_be_enabled()
            page.locator("#cancel-task").click()
            expect(page.locator("#task-header")).to_contain_text("Cancelled", timeout=10000)
            assert call("get_task", task_id=second)["task"]["status"] == "cancelled"
            page.locator("#mailbox-settings").evaluate("e => e.open = true")
            page.locator(".workspace-picker").evaluate("e => e.open = true")
            page.locator(".room-nav").filter(has_text=other["name"]).click()
            expect(page.locator(f'[data-task-id="{tid}"]')).to_have_count(0)
            expect(page.locator("#task-thread")).not_to_be_visible()
            page.locator("#task-view").click()
            page.locator("#new-task").click()
            expect(page.locator("#task-workers input:checked")).to_have_count(0)
            expect(page.locator("#create-task")).to_be_disabled()
            for checkbox in page.locator("#task-workers input").all():
                checkbox.check()
            expect(page.locator("#task-budget")).to_have_value(
                str(page.locator("#task-workers input:checked").count())
            )
            page.locator("#task-title").fill("DEMO · Web-origin task")
            page.locator("#task-context").fill("A local demo, no real bot account connected.")
            for index, field in enumerate(page.locator("#task-workers textarea").all()):
                field.fill(f"DEMO independent instruction {index + 1}")
            page.locator("#create-task").click()
            expect(page.locator("#task-create-dialog")).not_to_be_visible()
            expect(page.locator("#task-header")).to_contain_text("Web-origin task")
            store.handoffs.demo_tick()
            refresh()
            expect(page.locator("#task-header")).to_contain_text("Completed", timeout=10000)
            webtid = store.handoffs.listing(other["id"], "user")[0]["task"]["id"]
            call("get_task", fail=True, task_id=webtid)
            # Errors remain visible while the discussion composer is hidden.
            page.route(
                "**/tasks/context",
                lambda route: route.fulfill(
                    status=409, content_type="application/json", body='{"error":"requestFailed"}'
                ),
            )
            page.locator("#task-note").fill("Error visibility check")
            page.locator("#task-note-form button[type=submit]").click()
            expect(page.locator("#error")).to_be_visible()
            expect(page.locator("#error")).not_to_be_empty()
            page.unroute("**/tasks/context")
            page.locator("#task-note").fill("")
            page.evaluate("document.getElementById('error').textContent = ''")
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#language").select_option("zh")
            expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
            page.locator("#task-header").scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / "desktop-zh.png"))
            if not page.locator("#mailbox-settings").evaluate("e => e.open"):
                page.locator("#mailbox-settings > summary").click()
            page.locator("#language").select_option("en")
            page.screenshot(path=str(artifacts / "desktop-en.png"))
            assert not errors, errors
            if os.environ.get("HANDOFF_RECORD"):
                video_context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                )
                demo = video_context.new_page()
                recorder = subprocess.Popen(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-f",
                        "image2pipe",
                        "-vcodec",
                        "png",
                        "-framerate",
                        "10",
                        "-i",
                        "-",
                        "-an",
                        "-c:v",
                        "libvpx-vp9",
                        "-pix_fmt",
                        "yuv420p",
                        str(artifacts / "native-handoffs-demo.webm"),
                    ],
                    stdin=subprocess.PIPE,
                )

                def hold(milliseconds):
                    for _ in range(milliseconds // 100):
                        recorder.stdin.write(demo.screenshot())
                        demo.wait_for_timeout(100)

                demo.goto(f"http://127.0.0.1:{server.server_port}")
                # Ephemeral test auth stays in memory; never render a credential input in this video.
                demo.evaluate("(token) => { adminToken = token; return reloadWorkspace(); }", admin)
                demo.locator("#mailbox-settings").evaluate("e => e.open = true")
                demo.locator(".workspace-picker").evaluate("e => e.open = true")
                demo.locator(".room-nav").filter(has_text=room["name"]).click()
                demo.locator("#task-view").click()
                demo_id = create("DEMO · Native entry → two bot handoffs")
                demo.evaluate("() => refresh(true)")
                demo.locator(f'[data-task-id="{demo_id}"]').click()
                expect(demo.locator("#task-header")).to_contain_text(demo_id)
                hold(2000)
                items = [
                    next(
                        x for x in clients.call(a, "receive_assignments") if x["task_id"] == demo_id
                    )
                    for a in ids[1:]
                ]
                leases = [
                    clients.call(
                        a,
                        "claim_assignment",
                        task_id=demo_id,
                        assignment_id=item["id"],
                        expected_attempt=0,
                        request_id=secrets.token_hex(12),
                    )
                    for a, item in zip(ids[1:], items)
                ]
                demo.locator(f'[data-assignment-id="{items[0]["id"]}"]').click()
                report(
                    ids[1],
                    items[0],
                    leases[0],
                    "progress",
                    "DEMO: reviewing keyboard focus and readable handoff states.",
                )
                demo.evaluate("() => refresh(true)")
                expect(demo.locator("#handoff-events")).to_contain_text(
                    "reviewing keyboard focus", timeout=10000
                )
                demo.locator("#task-header").scroll_into_view_if_needed()
                hold(2200)
                demo.screenshot(path=str(artifacts / "native-progress-en.png"))
                report(
                    ids[1],
                    items[0],
                    leases[0],
                    "completed",
                    "DEMO: keyboard navigation and clear status text verified.",
                )
                report(
                    ids[2],
                    items[1],
                    leases[1],
                    "completed",
                    "DEMO: independent assignments and room isolation verified.",
                )
                demo.evaluate("() => refresh(true)")
                expect(demo.locator("#task-header")).to_contain_text("Completed", timeout=10000)
                demo.locator("#assignment-switch button").first.click()
                demo.locator("#task-header").scroll_into_view_if_needed()
                hold(2200)
                demo.screenshot(path=str(artifacts / "native-completed-en.png"))
                if not demo.locator("#mailbox-settings").evaluate("e => e.open"):
                    demo.locator("#mailbox-settings > summary").click()
                demo.locator("#language").select_option("zh")
                demo.screenshot(path=str(artifacts / "native-completed-zh.png"))
                demo.locator(f'[data-assignment-id="{items[0]["id"]}"]').click()
                demo.locator("#task-note").scroll_into_view_if_needed()
                demo.screenshot(path=str(artifacts / "native-result-zh.png"))
                if not demo.locator("#mailbox-settings").evaluate("e => e.open"):
                    demo.locator("#mailbox-settings > summary").click()
                demo.locator("#language").select_option("en")
                demo.locator("#task-note").scroll_into_view_if_needed()
                demo.screenshot(path=str(artifacts / "native-result-en.png"))
                if not demo.locator("#mailbox-settings").evaluate("e => e.open"):
                    demo.locator("#mailbox-settings > summary").click()
                demo.locator("#language").select_option("zh")
                hold(2000)
                cancel_id = create("DEMO · Stop pending handoffs")
                demo.locator("#task-back").click()
                demo.evaluate("() => refresh(true)")
                demo.locator(f'[data-task-id="{cancel_id}"]').click()
                expect(demo.locator("#cancel-task")).to_be_enabled()
                demo.locator("#cancel-task").click()
                hold(2000)
                recorder.stdin.close()
                assert recorder.wait(30) == 0
                video_context.close()
            context.close()
            browser.close()
        print(
            "PASS: real stdio MCP + browser task identity, independent workers, progress/context/XSS, retry/fan-in, delayed navigation, cancellation, room isolation, Web demo, EN/ZH"
        )
    finally:
        clients.close()
        server.shutdown()
        thread.join()
        server.server_close()


if __name__ == "__main__":
    main()
