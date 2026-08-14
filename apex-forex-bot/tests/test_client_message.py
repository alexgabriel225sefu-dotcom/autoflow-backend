"""Driving the bot as the client, without a remote shell over the account.

The command dispatch lived inside the getUpdates poll loop, so the only way
to exercise a command was for a person to type it. Remote verification meant
reading the code and hoping — which is how a promised /settings and a
promised /resume both shipped without existing.

dispatch_command() is that same block, extracted. The poll loop calls it with
the arguments it used to compute inline, so a real message takes the
identical path; an injected one takes it too. A test that ran a private copy
of this logic would prove nothing about what a client actually gets.

The capability is deliberately narrower than a client: acting as somebody
inside their own account is close enough to a remote shell that the
destructive and money-moving commands have to stay out of it.

Run: python tests/test_client_message.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-msg-")

from apex import telegram as tg  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


print("\n── the dispatch is reachable, and it is the SAME one ──")
check("dispatch_command exists at module level",
      callable(getattr(tg, "dispatch_command", None)))
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "telegram.py"), encoding="utf-8").read()
check("the poll loop calls it rather than keeping its own copy",
      "dispatch_command(chat_id, raw, msg_id, first_line, cmd_l, args)" in SRC)
check("there is exactly one dispatch chain in the file",
      SRC.count('elif cmd_l in ("/status", "/s"):') == 1,
      str(SRC.count('elif cmd_l in ("/status", "/s"):')))
check("and it lives inside the extracted function, not the poll loop",
      SRC.index("def dispatch_command") < SRC.index('elif cmd_l in ("/status", "/s"):'))
check("no loop-only `continue` survived the extraction",
      "'continue' not properly in loop" not in SRC)

print("\n── it parses a raw line the way the poll loop did ──")
seen = []
tg.send_to = lambda cid, text, **kw: seen.append((str(cid), text)) or text
tg.access.is_admin = lambda cid: False
tg.access.is_allowed = lambda cid: True

seen.clear()
tg.dispatch_command("999", "/help")
check("a bare command reaches its handler", bool(seen), "nothing was sent")
check("and it is the short card, not the 24-line wall",
      seen and "How this works" in seen[0][1], (seen[0][1][:60] if seen else ""))

seen.clear()
tg.dispatch_command("999", "/verbose")
check("a command with side effects runs", bool(seen))

seen.clear()
tg.dispatch_command("999", "/strategy momentum")
check("arguments are parsed off the same line", bool(seen))
check("the reply names the strategy in plain language",
      seen and "Momentum" in seen[-1][1], (seen[-1][1][:80] if seen else ""))

seen.clear()
tg.dispatch_command("999", "/nonsense_command")
check("an unknown command is ignored, not crashed on", True)

print("\n── the deny list keeps this from being a remote shell ──")
import re  # noqa: E402

CA = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "apex", "control_actions.py"), encoding="utf-8").read()
deny_block = CA[CA.index("_MSG_DENY = {"):CA.index("def h_client_message")]
for cmd, why in (("/reset", "disconnects the broker and wipes settings"),
                 ("/paper", "the real-money switch"),
                 ("/env", "routes to /paper"),
                 ("/setkeys", "credential rotation"),
                 ("/deploy", "ships code"),
                 ("/grant", "access control"),
                 ("/revoke", "access control"),
                 ("/buy", "use the audited force_trade"),
                 ("/sell", "use the audited force_trade"),
                 ("/close", "use the audited force_close")):
    check(f"{cmd} is refused — {why}", f'"{cmd}"' in deny_block, deny_block[:120])

check("the handler checks the deny list before dispatching",
      CA.index("if cmd in _MSG_DENY") < CA.index("tg.dispatch_command(uid, text)"))
check("it matches on the COMMAND, not a substring of the text",
      "text.split()[0].lower()" in CA)
check("a @botname suffix cannot slip a denied command through",
      '.split("@")[0]' in CA[CA.index("def h_client_message"):])
check("empty text is rejected", 'raise ValueError("text is required")' in CA)
check("absurdly long text is rejected", "text too long" in CA)
check("every injected message is recorded in the audit feed",
      'control.event("mcp_msg"' in CA)

print("\n── the MCP tool exposes it with the limits stated ──")
SRV = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "ruflo-mcp", "server.py"),
    encoding="utf-8").read()
check("the tool is registered", "def client_message(" in SRV)
check("it routes to the control action", '"client_message"' in SRV)
check("its docstring names what is refused",
      "REFUSED, by design" in SRV and "/reset" in SRV)
check("and points at the audited alternatives for trades",
      "open_trade / force_close" in SRV)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL CLIENT-MESSAGE CHECKS PASSED.")
