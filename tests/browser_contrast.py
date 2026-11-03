"""Computed text contrast regression on synthetic light/dark mailbox surfaces.

Uses WCAG 2.2 SC 1.4.3 luminance ratios, not screenshot antialiasing.
Not a full accessibility conformance audit (images/native popup UI excluded).
"""

import http.client
import json
import os
import secrets
import threading

from playwright.sync_api import sync_playwright
from roundtable import Store
from server import make_server

AUDIT = r"""() => {
 const canvas=document.createElement('canvas'); canvas.width=canvas.height=1;
 const ctx=canvas.getContext('2d',{willReadFrequently:true});
 const rgba=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data].map(v=>v/255);};
 const blend=(fg,bg)=>fg.slice(0,3).map((v,i)=>v*fg[3]+bg[i]*(1-fg[3])).concat(1);
 const lum=c=>c.slice(0,3).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
 const ratio=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
 const rows=[];
 for(const el of document.querySelectorAll('body *')){
  if(el.closest('[disabled],[aria-hidden=true],svg,option,script,style'))continue;
  if(!el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}))continue;
  const rect=el.getBoundingClientRect();if(!rect.width||!rect.height)continue;
  const text=[...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim();
  const input=el.matches('input:not([type=checkbox]):not([type=hidden]),textarea');
  if(!text&&!input)continue;
  let chain=[],p=el;while(p){chain.unshift(p);p=p.parentElement;}
  let bg=[1,1,1,1],opacity=1;
  for(const n of chain){const s=getComputedStyle(n);bg=blend(rgba(s.backgroundColor),bg);opacity*=Number(s.opacity);}
  if(opacity===0)continue;
  const style=getComputedStyle(el);const placeholder=input&&!el.value&&el.placeholder;
  const inkStyle=placeholder?getComputedStyle(el,'::placeholder'):style;
  const color=rgba(inkStyle.color);color[3]*=opacity*(placeholder?Number(inkStyle.opacity):1);
  const contrast=ratio(blend(color,bg),bg);
  const size=parseFloat(style.fontSize);const large=size>=24||(size>=18.6667&&Number(style.fontWeight)>=700);
  rows.push({node:el.id||el.className||el.tagName,text:(text||el.value||el.placeholder||'').slice(0,45),ratio:contrast,min:large?3:4.5,size});
 }
 return rows;
}"""


def main():
    store = Store()
    for bot in ("atlas", "nova"):
        store.register_bot(bot, bot.title(), "mailbox")
    room = store.create_group("Synthetic workspace", ["atlas", "nova"])
    topic = store.mailboxes.roundtable(room["id"])
    for actor in ("user", "bot:atlas", "bot:nova"):
        store.mailboxes.post(
            room["id"],
            actor,
            topic["id"],
            {"body": "Synthetic review message", "request_id": actor},
        )
    store.handoffs.create(
        room["id"],
        "user",
        {
            "title": "合成任务",
            "context": "检查界面文字。",
            "assignments": [{"worker": "nova", "instruction": "记录检查结果。"}],
            "budget": 4,
            "request_id": "contrast-task",
        },
    )
    admin = secrets.token_urlsafe(48)
    server = make_server(store, admin, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    failures = []
    total = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
            for theme in ("light", "dark"):
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000},
                    locale="zh-CN",
                    reduced_motion="reduce",
                )
                page = context.new_page()
                page.add_init_script(f"localStorage.setItem('roundtable-theme','{theme}')")
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
                conn.request(
                    "POST",
                    "/api/ui-login/issue",
                    "{}",
                    {"Authorization": "Bearer " + admin, "Content-Type": "application/json"},
                )
                code = json.loads(conn.getresponse().read())["code"]
                conn.close()
                page.goto(origin + "/#roundtable-login=" + code)
                page.locator(".mailbox-message").first.wait_for()

                def check(label):
                    nonlocal total
                    rows = page.evaluate(AUDIT)
                    total += len(rows)
                    failures.extend(
                        {"theme": theme, "surface": label, **r}
                        for r in rows
                        if r["ratio"] < r["min"] or r["size"] < 12
                    )

                check("roundtable")
                page.locator("#mailbox-settings > summary").click()
                check("settings")
                page.keyboard.press("Escape")
                page.locator(".mailbox-message").last.hover()
                check("message hover")
                for target in ("directory", "manage", "mcp-open"):
                    if target != "directory":
                        page.locator("#mailbox-settings > summary").click()
                    page.locator("#" + target).click()
                    page.locator("dialog[open]").wait_for()
                    check(target)
                    page.locator("dialog[open] .close").click()
                    page.locator("dialog[open]").wait_for(state="hidden")
                page.locator("#directory").click()
                page.locator("#bot-add").click()
                page.locator("#bot-name").fill("Helper")
                page.locator("#bot-id").fill("helper-" + theme)
                check("Bot editor")
                page.locator("#bot-save").click()
                page.locator("#bot-token-dialog").wait_for(state="visible")
                page.locator("#bot-created-token").evaluate("n => n.textContent='凭据已隐藏'")
                check("one-time token")
                page.locator("#bot-token-dialog .close").click()
                bot = page.locator(f'[data-bot-id="helper-{theme}"]')
                bot.get_by_role("button", name="删除 Bot", exact=True).click()
                page.locator("#bot-delete-confirm").fill("Helper")
                check("delete confirmation")
                page.locator("#bot-delete-dialog .close").click()
                page.locator("#directory-dialog .close").click()
                page.locator(".task-card").first.click()
                page.locator("#task-header").wait_for()
                check("task details")
                page.locator("#task-back").click()
                page.locator("#delegate-topic").click()
                check("delegate")
                page.locator("dialog[open] .close").click()
                context.close()
            browser.close()
        assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)
        print(f"Contrast checks passed: {total} text samples across light/dark surfaces")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.db.close()


if __name__ == "__main__":
    main()
