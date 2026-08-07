#!/usr/bin/env python3
"""Local preference-labeling UI for the persona plugin. Standard library only.

Mines your own writing out of Claude Code transcripts, serves a labeling UI on
localhost, and keeps every label in one JSON file. Nothing leaves the machine:
there is no network call in this file except the loopback HTTP server.

    persona.py harvest                 # mine ~/.claude/projects for your writing
    persona.py harvest --from ~/notes  # ...and any other prose you've written
    persona.py serve --mode critique   # label which snippets sound like you
    persona.py serve --mode turing     # blind: did you write this, or Claude?
    persona.py candidates < items.json # add subagent-written attempts
    persona.py status                  # where you are in the loop
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

# Overridable so a test run cannot clobber real labels. It can: this default
# was wiped once by a `rm -rf` in a smoke test, taking 44 critiques with it.
STATE = Path(os.environ.get("PERSONA_STATE") or Path.home() / ".claude" / "persona" / "state.json")
PROJECTS = Path(os.environ.get("PERSONA_PROJECTS") or Path.home() / ".claude" / "projects")

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
        b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    )


def is_prose(text):
    """Whether a chunk of text is someone writing, rather than pasted material."""
    text = text.strip()
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
    return is_prose(_blocks_to_text(msg.get("content")))


def _key(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def load():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"version": 1, "items": [], "fooled": 0}


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def _add(state, seen, text, source="corpus"):
    """Record a snippet if it is prose we haven't already got."""
    text = text.strip()
    k = _key(text)
    if k in seen or not is_prose(text):
        return False
    seen.add(k)
    state["items"].append(
        {
            "id": f"c{len(state['items'])}",
            "text": text,
            "source": source,
            "round": 0,
            "critique": None,
            "guess": None,
        }
    )
    return True


def harvest_files(state, roots, limit):
    """Add prose from your own writing outside Claude Code.

    Transcripts are one register -- you instructing a model. A voice skill built
    on them alone is guessing everywhere else, which is what round 1 of the
    original run demonstrated. Point this at notes, drafts, posts, anything you
    wrote as yourself.
    """
    seen = {_key(i["text"]) for i in state["items"]}
    found = 0
    for root in roots:
        root = Path(root).expanduser()
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for f in files:
            if f.suffix.lower() not in {".md", ".txt", ".markdown", ""} or not f.is_file():
                continue
            try:
                body = f.read_text(errors="replace")
            except OSError:
                continue
            # Blank-line paragraphs are the closest thing to a message boundary
            # in a document. ponytail: no markdown parser for a split().
            for para in re.split(r"\n\s*\n", body):
                if _add(state, seen, para):
                    found += 1
                    if found >= limit:
                        return found
    return found


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
            if _add(state, seen, _blocks_to_text(event["message"]["content"])):
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
    judged = [i for i in corpus if i["critique"]]
    return {
        "corpus_total": len(corpus),
        # Split by verdict: the negatives are worth more than the positives,
        # and burying them in one list is how they get skimmed past.
        "sounds_like_me": [i for i in judged if i["critique"]["verdict"] == "mine"],
        "not_like_me": [i for i in judged if i["critique"]["verdict"] == "not-mine"],
        "nothing_to_judge": sum(1 for i in judged if i["critique"]["verdict"] == "skip"),
        "unlabeled": len(corpus) - len(judged),
        "candidates_total": len(cands),
        "candidates_judged": len(guessed),
        # A "fool" is a candidate the user attributed to themselves.
        "fooled": sum(1 for i in guessed if i["guess"]["said"] == "mine"),
        "missed": [i for i in guessed if i["guess"]["said"] == "claude"],
    }


def status(state):
    """Where you are in the loop, in one screen."""
    r = report(state)
    fooled, need = r["fooled"], 3
    lines = [
        f"corpus            {r['corpus_total']} snippets ({r['unlabeled']} unlabeled)",
        f"  sounds like me  {len(r['sounds_like_me'])}",
        f"  not like me     {len(r['not_like_me'])}",
        f"  nothing to judge {r['nothing_to_judge']}",
        f"candidates        {r['candidates_total']} ({r['candidates_judged']} judged)",
        f"fooled            {fooled} / {need}",
        "",
    ]
    if not r["corpus_total"]:
        lines.append("next: persona.py harvest")
    elif r["unlabeled"] == r["corpus_total"]:
        lines.append("next: persona.py serve --mode critique")
    elif not r["candidates_total"] or r["candidates_judged"] == r["candidates_total"]:
        if fooled >= need:
            lines.append("done: the voice skill passed. nothing left to label.")
        else:
            lines.append("next: ask Claude for a new round of candidates")
    else:
        lines.append("next: persona.py serve --mode turing")
    if r["corpus_total"] and not r["not_like_me"]:
        lines.append(
            "note: no 'not like me' labels yet. one is worth several positives,\n"
            "      since every rule is otherwise induced from what you approved."
        )
    return "\n".join(lines)


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
    "Your own words, pulled from your transcripts. Mark the ones that read as "
    + "characteristically you, and say what is off about the ones that don't."],
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
      ' labeled. The server has stopped; tell Claude you are finished.</div>';
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
        '<button data-v=skip>Nothing to judge</button></div>'
      : '<div class=row><button data-v=mine>I wrote this</button>' +
        '<button data-v=claude>Claude wrote this</button></div>');
  // textContent, not innerHTML: transcript text is data and must never be
  // parsed as markup.
  app.querySelector(".text").textContent = it.text;
  // Skip records a verdict rather than just advancing. An unrecorded skip is
  // indistinguishable from an item you never reached, which throws away the
  // only weak negative signal most people produce.
  app.querySelectorAll("button").forEach(b => b.onclick = () => {
    const note = document.getElementById("note");
    send(it.id, MODE === "critique"
      ? {critique:{verdict:b.dataset.v, note: note ? note.value : ""}}
      : {guess:{said:b.dataset.v}});
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
    field = "critique" if mode == "critique" else "guess"

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
                remaining = sum(1 for i in queue if not i[field])
            self._send(b"{}", "application/json")
            # Stop once the queue is labeled. Leaving it running means the user
            # has to find the terminal and ctrl-c, and an agent that started it
            # in the background leaves an orphan holding the port.
            if not remaining:
                threading.Thread(target=srv.shutdown, daemon=True).start()

        def log_message(self, *a):
            pass  # the UI is the interface; access logs are noise

    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"labeling {len(queue)} items at {url}", flush=True)
    print("stops on its own when you finish, or ctrl-c to stop early", flush=True)
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    print("\nlabels saved to", STATE, flush=True)


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

    # Verdicts split three ways, and a skip is recorded rather than dropped.
    def crit(v):
        return {"id": v, "source": "corpus", "critique": {"verdict": v}, "guess": None}

    s = {"version": 1, "items": [crit("mine"), crit("not-mine"), crit("skip")]}
    r = report(s)
    assert len(r["sounds_like_me"]) == 1 and len(r["not_like_me"]) == 1
    assert r["nothing_to_judge"] == 1 and r["unlabeled"] == 0

    # --from splits documents on blank lines and reuses the prose filter.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "notes.md").write_text(f"{'a' * 100}\n\n    pasted code\n\ntoo short\n\n{'b' * 100}")
        st = {"version": 1, "items": []}
        assert harvest_files(st, [d], 10) == 2, "only the two prose paragraphs"
    print("selftest ok")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selftest", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    h = sub.add_parser("harvest")
    h.add_argument("--limit", type=int, default=60)
    h.add_argument(
        "--from",
        dest="sources",
        action="append",
        default=[],
        metavar="PATH",
        help="also mine .md/.txt under this file or directory (repeatable). "
        "transcripts are one register; your own notes and drafts are others.",
    )
    s = sub.add_parser("serve")
    s.add_argument("--mode", choices=["critique", "turing"], default="critique")
    s.add_argument("--port", type=int, default=8765)
    c = sub.add_parser("candidates")
    c.add_argument("--round", type=int, default=1)
    sub.add_parser("report")
    sub.add_parser("status")
    args = p.parse_args()

    if args.selftest:
        return selftest()

    state = load()
    if args.cmd == "harvest":
        n = harvest(state, args.limit)
        if args.sources:
            n += harvest_files(state, args.sources, max(0, args.limit - n))
        save(state)
        print(f"harvested {n} new snippets ({len(state['items'])} total) -> {STATE}")
        if not args.sources:
            print(
                "tip: --from ~/notes (or any dir of your own .md/.txt) widens the\n"
                "     corpus past 'you instructing an agent', which is the one\n"
                "     register transcripts contain."
            )
        print("\n" + status(state))
    elif args.cmd == "serve":
        serve(state, args.mode, args.port)
    elif args.cmd == "candidates":
        add_candidates(state, json.load(sys.stdin), args.round)
        save(state)
        print(f"added candidates -> {STATE}")
    elif args.cmd == "report":
        print(json.dumps(report(state), indent=2))
    elif args.cmd == "status":
        print(status(state))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
