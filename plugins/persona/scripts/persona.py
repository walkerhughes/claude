#!/usr/bin/env python3
"""Local preference-labeling UI for the persona plugin. Standard library only.

Mines your own writing out of Claude Code transcripts, serves a labeling UI on
localhost, and keeps every label in one JSON file. Nothing leaves the machine:
there is no network call in this file except the loopback HTTP server.

    persona.py harvest                 # mine ~/.claude/projects for your writing
    persona.py serve --mode critique   # label which snippets sound like you
    persona.py serve --mode turing     # blind: did you write this, or Claude?
    persona.py candidates < items.json # add subagent-written attempts
    persona.py report                  # labels + fool count, for Claude to read
    persona.py --selftest              # assert the harvest filters still work

ponytail: one file, no deps, no build step. A framework here would buy hot
reload for a form with three buttons.
"""

import argparse
import http.server
import json
import os
import re
import sys
import threading
import webbrowser
from pathlib import Path

STATE = Path.home() / ".claude" / "persona" / "state.json"
PROJECTS = Path.home() / ".claude" / "projects"

# Text that is in a user turn but was not typed by the user.
NOISE = (
    "<system-reminder>",
    "<command-name>",
    "<command-message>",
    "<local-command-stdout>",
    "[Request interrupted",
    "Caveat: The messages below",
    "<user-prompt-submit-hook>",
)
MIN_CHARS = 80  # shorter than this carries no style
MAX_CHARS = 2000  # longer than this is almost always pasted material


def _blocks_to_text(content):
    """The typed text of a user turn, or "" if it isn't plain typing.

    Content is either a string or a list of blocks. Only text blocks count --
    a tool_result block is the environment talking, not the user.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return ""
    return "\n".join(
        b["text"]
        for b in content
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    )


def is_user_prose(event):
    """Whether this transcript event is the user writing in their own voice."""
    if event.get("type") != "user":
        return False
    # Subagent transcripts are Claude prompting Claude. Their user turns are
    # written by the parent model, so harvesting them would teach the skill to
    # imitate Claude -- the exact opposite of the goal.
    if event.get("isSidechain"):
        return False
    msg = event.get("message") or {}
    if msg.get("role") != "user":
        return False
    text = _blocks_to_text(msg.get("content")).strip()
    if not text or any(n in text for n in NOISE):
        return False
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        return False
    # Pasted code, logs and diffs are not prose. Judge by how many lines look
    # like a person talking rather than by guessing at languages.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and sum(1 for ln in lines if re.match(r"^[\s{}\[\]<>|+\-*#/]", ln)) > 0.4 * len(lines):
        return False
    if text.count("```") >= 2:
        return False
    return True


def _key(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def load():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"version": 1, "items": [], "fooled": 0}


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def harvest(state, limit):
    """Add your own writing from every project transcript to the corpus."""
    seen = {_key(i["text"]) for i in state["items"]}
    found = 0
    for f in sorted(PROJECTS.rglob("*.jsonl")):
        # Skip the subagents/ sidecar files wholesale; see is_user_prose.
        if "subagents" in f.parts:
            continue
        for line in f.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not is_user_prose(event):
                continue
            text = _blocks_to_text(event["message"]["content"]).strip()
            k = _key(text)
            if k in seen:
                continue
            seen.add(k)
            state["items"].append(
                {
                    "id": f"c{len(state['items'])}",
                    "text": text,
                    "source": "corpus",
                    "round": 0,
                    "critique": None,
                    "guess": None,
                }
            )
            found += 1
            if found >= limit:
                return found
    return found


def add_candidates(state, texts, rnd):
    """Add subagent-written attempts at your voice, for the blind round."""
    for t in texts:
        state["items"].append(
            {
                "id": f"g{len(state['items'])}",
                "text": t.strip(),
                "source": "candidate",
                "round": rnd,
                "critique": None,
                "guess": None,
            }
        )


def report(state):
    corpus = [i for i in state["items"] if i["source"] == "corpus"]
    cands = [i for i in state["items"] if i["source"] == "candidate"]
    guessed = [i for i in cands if i["guess"]]
    return {
        "corpus_total": len(corpus),
        "critiqued": [i for i in corpus if i["critique"]],
        "candidates_total": len(cands),
        "candidates_judged": len(guessed),
        # A "fool" is a candidate the user attributed to themselves.
        "fooled": sum(1 for i in guessed if i["guess"]["said"] == "mine"),
        "missed": [i for i in guessed if i["guess"]["said"] == "claude"],
    }


PAGE = """<!doctype html><meta charset=utf-8><title>persona</title>
<style>
:root{color-scheme:light dark;--bg:#fff;--fg:#111;--mut:#666;--line:#ddd;--acc:#2563eb}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--mut:#999;--line:#333;--acc:#60a5fa}}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1rem;background:var(--bg);color:var(--fg);
font:16px/1.6 ui-sans-serif,system-ui,-apple-system,sans-serif}
main{max-width:44rem;margin:0 auto}
h1{font-size:1rem;font-weight:600;margin:0 0 .25rem}
.sub{color:var(--mut);font-size:.85rem;margin-bottom:2rem}
.card{border:1px solid var(--line);border-radius:10px;padding:1.25rem;margin-bottom:1rem}
.text{white-space:pre-wrap;word-wrap:break-word}
.row{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:1rem}
button{font:inherit;padding:.45rem .9rem;border:1px solid var(--line);border-radius:7px;
background:transparent;color:var(--fg);cursor:pointer}
button:hover{border-color:var(--acc);color:var(--acc)}
textarea{width:100%;margin-top:.75rem;padding:.6rem;border:1px solid var(--line);
border-radius:7px;background:transparent;color:var(--fg);font:inherit;min-height:4rem}
.done{color:var(--mut);text-align:center;padding:3rem 0}
.tag{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
.ok{color:#16a34a}.no{color:#dc2626}
</style>
<main>
<h1 id=title></h1>
<div class=sub id=sub></div>
<div id=app></div>
</main>
<script>
const MODE = "__MODE__";
let items = [], i = 0;

const titles = {
  critique: ["Does this sound like you?",
    "Your own words, pulled from your transcripts. Mark the ones that read as characteristically you, and say what is off about the ones that don't."],
  turing: ["Who wrote this?",
    "Some of these you wrote. Some a subagent wrote trying to sound like you. No feedback until the end."],
};

async function load(){
  items = await (await fetch("/api/items")).json();
  [document.getElementById("title").textContent,
   document.getElementById("sub").textContent] = titles[MODE];
  render();
}

async function send(id, payload){
  await fetch("/api/label", {method:"POST", headers:{"content-type":"application/json"},
    body: JSON.stringify({id, ...payload})});
  i++; render();
}

function render(){
  const app = document.getElementById("app");
  if (i >= items.length){
    app.innerHTML = '<div class=done>Done &mdash; ' + items.length +
      ' labeled. Close this tab and tell Claude.</div>';
    return;
  }
  const it = items[i];
  app.innerHTML =
    '<div class=card><div class=tag>' + (i+1) + ' / ' + items.length + '</div>' +
    '<div class=text></div>' +
    (MODE === "critique"
      ? '<textarea id=note placeholder="What would you actually say here? What is off?"></textarea>' +
        '<div class=row><button data-v=mine>Sounds like me</button>' +
        '<button data-v=not-mine>Not how I would say it</button>' +
        '<button data-v=skip>Skip</button></div>'
      : '<div class=row><button data-v=mine>I wrote this</button>' +
        '<button data-v=claude>Claude wrote this</button></div>');
  // textContent, not innerHTML: transcript text is data and must never be
  // parsed as markup.
  app.querySelector(".text").textContent = it.text;
  app.querySelectorAll("button").forEach(b => b.onclick = () => {
    const v = b.dataset.v;
    if (v === "skip") { i++; return render(); }
    const note = document.getElementById("note");
    send(it.id, MODE === "critique"
      ? {critique:{verdict:v, note: note ? note.value : ""}}
      : {guess:{said:v}});
  });
}
load();
</script>
"""


def serve(state, mode, port):
    """Serve the labeling UI on loopback until the user stops it."""
    if mode == "critique":
        queue = [i for i in state["items"] if i["source"] == "corpus" and not i["critique"]]
    else:
        # Blind round: unjudged candidates, plus real snippets as true
        # positives. Without those the honest answer is always "Claude".
        queue = [i for i in state["items"] if i["source"] == "candidate" and not i["guess"]]
        reals = [i for i in state["items"] if i["source"] == "corpus" and not i["guess"]]
        queue += reals[: max(1, len(queue))]
        # Deterministic shuffle: no seed to thread, no import to justify.
        queue.sort(key=lambda x: _key(x["text"])[::-1])
    if not queue:
        print(f"nothing to label in {mode} mode; run harvest or candidates first")
        return
    by_id = {i["id"]: i for i in state["items"]}
    lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body, ctype):
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/items":
                payload = [{"id": i["id"], "text": i["text"]} for i in queue]
                self._send(json.dumps(payload).encode(), "application/json")
            elif self.path == "/":
                self._send(PAGE.replace("__MODE__", mode).encode(), "text/html; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/api/label":
                return self.send_error(404)
            n = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(n))
            with lock:
                item = by_id.get(body["id"])
                if item:
                    if "critique" in body:
                        item["critique"] = body["critique"]
                    if "guess" in body:
                        said = body["guess"]["said"]
                        item["guess"] = {
                            "said": said,
                            "correct": (said == "mine") == (item["source"] == "corpus"),
                        }
                    save(state)
            self._send(b"{}", "application/json")

        def log_message(self, *a):
            pass  # the UI is the interface; access logs are noise

    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"labeling {len(queue)} items at {url}  (ctrl-c when done)")
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped; labels saved to", STATE)


def selftest():
    def ev(content, **kw):
        return {"type": "user", "message": {"role": "user", "content": content}, **kw}

    prose = "x" * 90
    assert is_user_prose(ev(prose))
    assert not is_user_prose(ev(prose, isSidechain=True)), "subagent turns are Claude's words"
    assert not is_user_prose(ev("too short"))
    assert not is_user_prose(ev("x" * (MAX_CHARS + 1)))
    assert not is_user_prose(ev(f"<system-reminder>{prose}</system-reminder>"))
    assert not is_user_prose(ev(prose, type="assistant"))
    assert not is_user_prose(ev([{"type": "tool_result", "content": prose}]))
    assert is_user_prose(ev([{"type": "text", "text": prose}]))
    assert not is_user_prose(ev("\n".join(["    indented"] * 10))), "pasted code is not prose"
    assert not is_user_prose(ev(f"```\n{prose}\n```"))
    # A guess is only "correct" when it matches the item's true source.
    s = {"version": 1, "items": [{"id": "g0", "source": "candidate", "guess": {"said": "mine"}}]}
    assert report(s)["fooled"] == 1
    s["items"][0]["guess"] = {"said": "claude"}
    assert report(s)["fooled"] == 0
    print("selftest ok")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selftest", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    h = sub.add_parser("harvest")
    h.add_argument("--limit", type=int, default=60)
    s = sub.add_parser("serve")
    s.add_argument("--mode", choices=["critique", "turing"], default="critique")
    s.add_argument("--port", type=int, default=8765)
    c = sub.add_parser("candidates")
    c.add_argument("--round", type=int, default=1)
    sub.add_parser("report")
    args = p.parse_args()

    if args.selftest:
        return selftest()

    state = load()
    if args.cmd == "harvest":
        n = harvest(state, args.limit)
        save(state)
        print(f"harvested {n} new snippets ({len(state['items'])} total) -> {STATE}")
    elif args.cmd == "serve":
        serve(state, args.mode, args.port)
    elif args.cmd == "candidates":
        add_candidates(state, json.load(sys.stdin), args.round)
        save(state)
        print(f"added candidates -> {STATE}")
    elif args.cmd == "report":
        print(json.dumps(report(state), indent=2))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
