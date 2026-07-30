"""E2E: drive the real console UI in headless Chrome via CDP. NOT part of the
offline unit run (no test_ prefix) — run by hand / by an agent:

    PYTHONPATH=~/claude ~/claude/.venv/bin/python \
        ~/claude/marketing_manager/tests/e2e_console.py

Covers what unit tests can't: the onboarding dialog actually appearing on first
launch, tour menu, guide markdown rendering, localStorage persistence, and that
a hostile campaign name / schedule text is rendered inert (the stored-XSS fix).
Needs: Google Chrome, a free port, no network. State goes to a temp dir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PORT = 9333
TOKEN = "e2e-test-token"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


class Page:
    """Tiny CDP driver: evaluate JS in the first page target."""

    def __init__(self, ws_url: str):
        from websocket import create_connection
        self.ws = create_connection(ws_url, timeout=15, suppress_origin=True)
        self._id = 0

    def rpc(self, method: str, params: dict | None = None):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self._id:
                return m

    def js(self, expr: str, await_promise: bool = False):
        r = self.rpc("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                          "awaitPromise": await_promise})
        res = r.get("result", {}).get("result", {})
        if r.get("result", {}).get("exceptionDetails"):
            return {"__error__": r["result"]["exceptionDetails"].get("text", "js error")}
        return res.get("value")


def wait_for(page: Page, expr: str, timeout: float = 10.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if page.js(expr):
            return True
        time.sleep(0.25)
    return False


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="mm_e2e_")
    env = dict(os.environ,
               MARKETING_CONSOLE_TOKEN=TOKEN,
               MARKETING_MANAGER_HOME=os.path.join(tmp, "state"),
               MARKETING_CONSOLE_BRAND="RenWay",
               MARKETING_CONSOLE_GREETING="Hey, I'm RenWay — and I am Ren's way. Get to know me.",
               MARKETING_CONSOLE_GUIDE=os.path.expanduser("~/claude/renway/GUIDE.md"))

    from marketing_manager import server  # noqa: PLC0415 — after env is set
    os.environ.update({k: env[k] for k in env})
    srv = server.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    chrome = subprocess.Popen(
        [CHROME, "--headless=new", f"--remote-debugging-port={CDP_PORT}",
         f"--user-data-dir={os.path.join(tmp, 'chrome')}", "--no-first-run", base],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        page = None
        for _ in range(40):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json"))
                t = next((t for t in tabs if t.get("type") == "page"), None)
                if t:
                    page = Page(t["webSocketDebuggerUrl"])
                    break
            except Exception:
                pass
            time.sleep(0.25)
        assert page, "no CDP page target"
        wait_for(page, "!!document.querySelector('#gate')")

        # --- login gate ---
        check("gate shown before login", page.js("!$('#gate').classList.contains('hide')"))
        page.js(f"$('#tok').value={TOKEN!r}; login()")
        check("login hides gate", wait_for(page, "$('#gate').classList.contains('hide')"))

        # --- first-launch welcome ---
        check("welcome dialog on first launch", wait_for(page, "!$('#wel').classList.contains('hide')"))
        check("greeting is branded", page.js("$('#welBox').innerText.includes(\"I'm RenWay\")"))
        check("header rebranded", page.js("$('#brand').textContent==='RenWay'"))
        page.js("tourMenu()")
        check("tour menu offers 6 tours",
              page.js("document.querySelectorAll('#welBox button.act').length===6"))
        check("drip tour present", page.js("$('#welBox').innerText.includes('drip campaign')"))

        # --- guide tab ---
        page.js("openGuide()")
        check("guide tab visible", page.js("$('#t-guide').classList.contains('on')"))
        check("guide markdown rendered to headings",
              page.js("$('#g-body').querySelectorAll('h2,h3,h4').length>5"))
        check("prompting section present",
              page.js("$('#g-body').innerText.includes('Say the outcome')"))
        check("welcome marked done", page.js("localStorage.getItem('mc_onboarded')==='1'"))

        # --- tour prefills chat ---
        page.js("localStorage.removeItem('mc_onboarded'); showWelcome(); tourMenu()")
        page.js("const c=window.chat; window.chat=()=>{}; startTour(0); window.chat=c")
        check("tour switches to chat tab", page.js("$('#t-chat').classList.contains('on')"))
        check("tour prefills tutorial prompt",
              page.js("$('#ch-msg').value.startsWith('TUTORIAL:') && $('#ch-msg').value.includes('drip campaign')"))

        # --- stored-XSS: hostile campaign name must render inert ---
        evil = "<img src=x onerror=window.__xss=1>&<b>bold</b>"
        page.js(f"call('POST','/api/campaigns',{{name:{evil!r},platforms:['bluesky'],"
                "steps:[{offset_days:0,text:'x'}]}).then(()=>loadCampaigns())", await_promise=False)
        check("campaign list renders", wait_for(page, "document.querySelectorAll('#cm-list .card').length>0"))
        time.sleep(0.5)
        check("XSS did not execute", page.js("window.__xss===undefined"))
        check("no injected elements", page.js("$('#cm-list').querySelectorAll('img,script').length===0"))
        check("hostile name shown as text", page.js("$('#cm-list').innerText.includes('<img')"))

        # --- schedule with hostile text ---
        page.js("call('POST','/api/schedule',{at:'2027-01-01T00:00:00Z',"
                "text:'<script>window.__xss2=1</script>',platforms:['bluesky']}).then(()=>loadSchedule())")
        check("schedule renders", wait_for(page, "document.querySelectorAll('#s-list .card').length>0"))
        check("schedule XSS inert", page.js("window.__xss2===undefined && $('#s-list').querySelectorAll('script').length===0"))

        # --- tick semantics: dry button previews, real tick needs confirm ---
        page.js("tick('campaigns',true)")
        check("dry tick shows preview note (nothing sent)",
              wait_for(page, "$('#cm-list').innerText.includes('Preview tick')"))
        page.js("window.__confirms=0; window.confirm=()=>{window.__confirms++;return false}; tick('campaigns',false)")
        time.sleep(1.0)
        check("real tick asks for confirmation", page.js("window.__confirms===1"))
        check("declined confirm sends nothing", page.js("!$('#cm-list').innerText.includes('▶')"))

        # --- md2html hardening ---
        check("md2html escapes script", page.js("!md2html('<script>x</script>').includes('<script>')"))
        check("md2html renders bold+code",
              page.js("md2html('**b** and `c`').includes('<b>b</b>') && md2html('`c`').includes('<code>c</code>')"))

        # --- esc helper ---
        check("esc escapes all metachars", page.js("esc('<\"&>')==='&lt;&quot;&amp;&gt;'"))

        # --- persistence: onboarded → no welcome on reload ---
        page.js("localStorage.setItem('mc_onboarded','1')")
        page.rpc("Page.enable"); page.rpc("Page.reload")
        time.sleep(1.5)
        wait_for(page, "$('#gate').classList.contains('hide')")  # token cached → auto-login
        time.sleep(1.0)
        check("no welcome after onboarding", page.js("$('#wel').classList.contains('hide')"))
    finally:
        chrome.terminate()
        srv.shutdown()

    print(f"\n{'ALL GREEN' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
