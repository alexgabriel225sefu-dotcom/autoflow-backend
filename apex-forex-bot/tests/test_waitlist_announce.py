"""The early-access announcement: what it sends, what it refuses, what it never repeats.

This is the one place the product writes to a list of strangers who trusted a
form with an address. The mistakes that matter are all one-directional, and
these checks are written to catch them in that direction:

  * a SECOND email to somebody who already got it (worse than a missing one);
  * an email to somebody who asked to be removed;
  * a send that nobody confirmed, or that was confirmed for a different list;
  * an address in a log, a result or a screen;
  * copy that promises an outcome.

Run: python3 tests/test_waitlist_announce.py
"""
import os
import sys
import tempfile
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-announce-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from apex.platform import store as _store               # noqa: E402
from apex.platform import waitlist as W                 # noqa: E402
from apex.platform import waitlist_announce as A        # noqa: E402

for _var in ("RESEND_API_KEY", "A4T_WAITLIST_FROM_EMAIL", "A4T_WAITLIST_REPLY_TO"):
    os.environ.pop(_var, None)

# Joining must not touch the network in a test, and neither does the logo check.
A._logo_reachable = lambda: True

# Joining must not touch the network in a test.
W.send_waitlist_email = lambda address, **kw: {"status": "not_configured"}

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def raises(code, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except A.AnnounceError as e:
        return e.code == code
    return False


GOOD_BODY = (
    "Early access to Apex4Traders is opening. Demo accounts come first, and "
    "live trading is not enabled yet. Write back if you have a question."
)
SUBJECT = "Apex4Traders early access is opening"
CONTACT = "contact@example.com"


def configure():
    os.environ["RESEND_API_KEY"] = "re_test_key"
    os.environ["A4T_WAITLIST_FROM_EMAIL"] = "Apex4Traders <hello@example.com>"


def unconfigure():
    for v in ("RESEND_API_KEY", "A4T_WAITLIST_FROM_EMAIL", "A4T_WAITLIST_REPLY_TO"):
        os.environ.pop(v, None)


class Mailer:
    """A fake provider that records what it was asked to send."""

    def __init__(self, fail_with=None):
        self.sent = []
        self.fail_with = fail_with or {}

    def __call__(self, payload):
        to = payload["to"][0]
        err = self.fail_with.get(to)
        if err is not None:
            raise err
        self.sent.append(payload)
        return f"msg_{len(self.sent)}"


def fresh_list(n):
    """n addresses, joined in a known order, on an empty list."""
    for key in list(_store._set_members(W._k_index())):
        _store._delete(key)
        _store._set_remove(W._k_index(), key)
    addrs = [f"person{i}@example.com" for i in range(n)]
    for i, a in enumerate(addrs):
        W.join(a, source="landing", now=1_000 + i)
    return addrs


def run(campaign="launch-1", **kw):
    kw.setdefault("remove_contact", CONTACT)
    kw.setdefault("lock", False)
    kw.setdefault("sleep", lambda s: None)
    return A.run(campaign, SUBJECT, GOOD_BODY, **kw)


# ---------------------------------------------------------------------------
print("\n[1] what may be sent at all")
check("a plain, honest body is accepted",
      A.validate_campaign("launch-1", SUBJECT, GOOD_BODY)["subject"] == SUBJECT)
for bad, why in (("", "empty id"), ("Launch 1", "spaces and capitals"),
                 ("x" * 41, "too long"), ("a/b", "a slash")):
    check(f"campaign id refused: {why}",
          raises("CAMPAIGN_INVALID", A.validate_campaign, bad, SUBJECT, GOOD_BODY))
check("a subject with a line break is refused (header injection)",
      raises("SUBJECT_INVALID", A.validate_campaign, "c", "hi\nBcc: x@y.com", GOOD_BODY))
check("an empty subject is refused",
      raises("SUBJECT_INVALID", A.validate_campaign, "c", "  ", GOOD_BODY))
check("an empty body is refused",
      raises("BODY_INVALID", A.validate_campaign, "c", SUBJECT, "   "))
check("an oversized body is refused",
      raises("BODY_INVALID", A.validate_campaign, "c", SUBJECT, "x" * 6000))
for words in ("guaranteed profit every month", "risk-free returns",
              "earn 20% a week", "passive income awaits"):
    check(f"copy that promises an outcome is refused: {words!r}",
          raises("COPY_FLAGGED", A.validate_campaign, "c", SUBJECT, words))
check("the copy check can be overridden knowingly, never silently",
      bool(A.validate_campaign("c", SUBJECT, "profit and loss are shown",
                               allow_copy_flags=True)))

# ---------------------------------------------------------------------------
print("\n[2] what an email looks like")
configure()
p = A.build_payload("someone@example.com", SUBJECT, GOOD_BODY, CONTACT)
check("sent from the configured sender", p["from"].endswith("<hello@example.com>"))
check("to exactly one recipient", p["to"] == ["someone@example.com"])
check("a text part and an HTML part", "html" in p and "text" in p)
check("carries no tags, tracking or attachments",
      not ({"tags", "attachments", "scheduled_at"} & set(p)))
check("the body is what the owner wrote", GOOD_BODY in p["text"])
check("says how to be taken off the list", CONTACT in p["text"]
      and "remove" in p["text"].lower())
check("offers a List-Unsubscribe header when the contact is an address",
      p.get("headers", {}).get("List-Unsubscribe") == f"<mailto:{CONTACT}>")
check("no header is invented when the contact is not an address",
      "headers" not in A.build_payload("a@b.com", SUBJECT, GOOD_BODY,
                                       "write to the founder"))
check("no removal contact, no email",
      raises("NO_REMOVE_CONTACT", A.build_payload, "a@b.com", SUBJECT, GOOD_BODY, ""))
os.environ["A4T_WAITLIST_REPLY_TO"] = "reply@example.com"
check("the reply-to is honoured when set",
      A.build_payload("a@b.com", SUBJECT, GOOD_BODY, CONTACT).get("reply_to")
      == "reply@example.com")
os.environ.pop("A4T_WAITLIST_REPLY_TO")
check("an address is masked, never printed whole",
      A.mask("alice@example.com") == "a***@e***.com"
      and "alice" not in A.mask("alice@example.com"))

# ---------------------------------------------------------------------------
print("\n[2b] the HTML part: logo on top, nothing about the recipient")
import re as _re                                         # noqa: E402

ha = A.build_payload("alice@example.com", SUBJECT, GOOD_BODY, CONTACT)["html"]
hb = A.build_payload("bob@example.org", SUBJECT, GOOD_BODY, CONTACT)["html"]
check("byte-identical for every recipient", ha == hb)
check("neither part contains the recipient's address",
      "alice@example.com" not in ha
      and "alice@example.com" not in A.build_payload(
          "alice@example.com", SUBJECT, GOOD_BODY, CONTACT)["text"])
imgs = _re.findall(r"<img\b[^>]*>", ha)
check("exactly one image, the logo, with alt text and a width",
      len(imgs) == 1 and 'alt="Apex4Traders"' in imgs[0]
      and f'width="{A.LOGO_WIDTH}"' in imgs[0], str(imgs))
check("the logo URL is the product's own, with no query string or token",
      A.LOGO_URL.startswith("https://www.apex4traders.com/")
      and "?" not in A.LOGO_URL and "#" not in A.LOGO_URL
      and f'src="{A.LOGO_URL}"' in imgs[0])
check("no script, iframe, form, style tag or remote stylesheet",
      not _re.search(r"<(script|iframe|form|link|style|object|embed)\b", ha, _re.I))
check("no tracking parameter anywhere", not _re.search(r"utm_|[?&]id=|\btrack", ha, _re.I))
check("the owner's words are all there", "Early access to Apex4Traders is opening" in ha)
check("the removal line is in the HTML too", CONTACT in ha and "removed" in ha)

link_body = ("See the platform at https://www.apex4traders.com/signup.\n\n"
             "- Connect a demo account\n- Write a rule\n\nThanks.")
hl = A.build_payload("a@b.com", SUBJECT, link_body, CONTACT)["html"]
hrefs = _re.findall(r'href="([^"]+)"', hl)
check("a link goes to exactly the URL the owner wrote, unwrapped",
      hrefs == ["https://www.apex4traders.com/signup"], str(hrefs))
check("and the full stop after it stays outside the link",
      ">https://www.apex4traders.com/signup</a>." in hl)
check("a '- ' paragraph becomes a list", "<ul" in hl and hl.count("<li") == 2)
hi = A.build_payload("a@b.com", SUBJECT, "What you can do today:\n- One\n- Two\n- Three",
                     CONTACT)["html"]
check("an intro line followed by '- ' lines becomes a paragraph and a list",
      "What you can do today:</p>" in hi and hi.count("<li") == 3, hi[-400:])
check("the dashes are not left in the text of a list item", "<li" in hi and "- One" not in hi)

evil = "<script>alert(1)</script> <b>x</b> & \"quoted\""
he = A.build_payload("a@b.com", SUBJECT, evil, CONTACT)["html"]
check("the owner's text is escaped, never trusted as markup",
      "<script>alert" not in he and "&lt;script&gt;" in he and "&amp;" in he)
check("--text-only sends no HTML part and no image",
      "html" not in A.build_payload("a@b.com", SUBJECT, GOOD_BODY, CONTACT, html=False))

# ---------------------------------------------------------------------------
print("\n[3] a dry run changes nothing")
addrs = fresh_list(5)
m = Mailer()
r = run(post=m)
check("dry run is the default", r["dryRun"] is True)
check("it says how many would be sent", r["planned"] == 5, str(r))
check("it sends nothing", m.sent == [])
check("it hands back the exact phrase that must be typed to send",
      r["confirmation"] == "SEND launch-1 TO 5", r.get("confirmation"))
check("and it records nothing on any entry",
      all("announced" not in (_store._read(k) or {})
          for k in _store._set_members(W._k_index())))
check("its sample is masked",
      all("***" in s for s in r["sample"]) and not any(a in str(r) for a in addrs))

# ---------------------------------------------------------------------------
print("\n[4] a real send needs the switch and the right phrase")
m = Mailer()
check("--send without a confirmation is refused",
      raises("CONFIRM_MISMATCH", run, send=True, post=m))
check("a confirmation for a different count is refused",
      raises("CONFIRM_MISMATCH", run, send=True, confirm="SEND launch-1 TO 4", post=m))
check("a confirmation for a different campaign is refused",
      raises("CONFIRM_MISMATCH", run, send=True, confirm="SEND other TO 5", post=m))
check("nothing went out on any refusal", m.sent == [])

unconfigure()
check("an unconfigured provider is refused, not skipped",
      raises("NOT_CONFIGURED", run, send=True, confirm="SEND launch-1 TO 5", post=m))
os.environ["RESEND_API_KEY"] = "re_x"
check("a half-configured provider is refused",
      raises("NOT_CONFIGURED", run, send=True, confirm="SEND launch-1 TO 5", post=m))
configure()

r = run(send=True, confirm="SEND launch-1 TO 5", post=m)
check("with the right phrase it sends to everyone, once", len(m.sent) == 5
      and sorted(x["to"][0] for x in m.sent) == sorted(addrs), str(len(m.sent)))
check("and reports counts", (r["sent"], r["failed"], r["unknown"]) == (5, 0, 0), str(r))
check("each entry is marked sent for this campaign, with the provider id",
      all((_store._read(k)["announced"]["launch-1"]["status"] == "sent"
           and _store._read(k)["announced"]["launch-1"].get("providerId"))
          for k in _store._set_members(W._k_index())))
check("the result carries no address", not any(a in str(r) for a in addrs))

m2 = Mailer()
r = run(post=m2)
check("running the same campaign again plans nobody", r["planned"] == 0, str(r))
r = run(send=True, confirm="SEND launch-1 TO 0", post=m2)
check("and sends nothing, even when forced", m2.sent == [] and r["sent"] == 0)
r = run(campaign="launch-2", post=Mailer())
check("a different campaign is a different send", r["planned"] == 5)

# ---------------------------------------------------------------------------
print("\n[5] a removed address is never written to")
fresh_list(3)
W.remove("person1@example.com")
m = Mailer()
r = run(send=True, confirm="SEND launch-1 TO 2", post=m)
check("the removed address is not on the plan or the send",
      sorted(x["to"][0] for x in m.sent) == ["person0@example.com", "person2@example.com"])

fresh_list(3)


class RemovesDuringSend(Mailer):
    """Somebody asks to be removed while the run is in progress."""

    def __call__(self, payload):
        out = super().__call__(payload)
        if len(self.sent) == 1:
            W.remove("person2@example.com")
        return out


m = RemovesDuringSend()
run(send=True, confirm="SEND launch-1 TO 3", post=m)
check("an address removed mid-run is skipped when its turn comes",
      "person2@example.com" not in [x["to"][0] for x in m.sent], str(len(m.sent)))

# ---------------------------------------------------------------------------
print("\n[6] an uncertain outcome is never retried by itself")
fresh_list(4)
boom = {
    "person1@example.com": TimeoutError("timed out"),
    "person2@example.com": urllib.error.HTTPError("u", 422, "bad", {}, None),
    "person3@example.com": urllib.error.HTTPError("u", 503, "down", {}, None),
}
m = Mailer(fail_with=boom)
r = run(send=True, confirm="SEND launch-1 TO 4", post=m, max_consecutive_failures=10)
state = {a: _store._read(W._key(a))["announced"]["launch-1"]["status"]
         for a in ("person0@example.com", "person1@example.com",
                   "person2@example.com", "person3@example.com")}
check("a timeout is 'unknown': it may have been delivered",
      state["person1@example.com"] == "unknown", str(state))
check("a 4xx is 'failed': the provider refused it, so nothing went out",
      state["person2@example.com"] == "failed", str(state))
check("a 5xx is 'unknown' as well", state["person3@example.com"] == "unknown")
check("the one that worked is 'sent'", state["person0@example.com"] == "sent")
check("counts add up", (r["sent"], r["failed"], r["unknown"]) == (1, 1, 2), str(r))

m = Mailer()
r = run(post=m)
check("a re-run plans nobody: unknown and failed are held back", r["planned"] == 0, str(r))
check("it says what it held back", r["held"] == {"failed": 1, "unknown": 2, "sending": 0}
      or (r["held"].get("failed") == 1 and r["held"].get("unknown") == 2), str(r.get("held")))
r = run(post=m, retry_failed=True)
check("--retry-failed brings back only the refused one", r["planned"] == 1)
r = run(post=m, retry_unknown=True)
check("--retry-unknown brings back only the uncertain ones", r["planned"] == 2)

# a crash between claim and answer leaves 'sending', which is also held
fresh_list(2)
k = W._key("person0@example.com")
rec = _store._read(k)
rec["announced"] = {"launch-1": {"status": "sending", "at": 1}}
_store._write(k, rec)
r = run(post=Mailer())
check("a 'sending' left by a crashed run is held, not resent", r["planned"] == 1
      and r["held"]["sending"] == 1, str(r))

# ---------------------------------------------------------------------------
print("\n[7] it stops when the provider is plainly down")
fresh_list(6)
down = {f"person{i}@example.com": urllib.error.HTTPError("u", 401, "no", {}, None)
        for i in range(6)}
m = Mailer(fail_with=down)
r = run(send=True, confirm="SEND launch-1 TO 6", post=m, max_consecutive_failures=3)
check("three failures in a row stop the run", r["stopped"] == "CONSECUTIVE_FAILURES"
      and r["failed"] == 3, str(r))
untouched = [a for a in (f"person{i}@example.com" for i in range(6))
             if "announced" not in _store._read(W._key(a))]
check("the rest are untouched, so they can go once it is fixed", len(untouched) == 3)

# ---------------------------------------------------------------------------
print("\n[8] a daily batch")
fresh_list(5)
m = Mailer()
r = run(limit=2, post=m)
check("the plan respects the limit", r["planned"] == 2 and r["remaining"] == 3, str(r))
r = run(limit=2, send=True, confirm="SEND launch-1 TO 2", post=m)
check("it sends the first two, oldest sign-up first",
      [x["to"][0] for x in m.sent] == ["person0@example.com", "person1@example.com"])
r = run(limit=2, send=True, confirm="SEND launch-1 TO 2", post=m)
check("the next run continues where it stopped",
      [x["to"][0] for x in m.sent][2:] == ["person2@example.com", "person3@example.com"])
check("a limit over the ceiling is refused",
      raises("LIMIT_INVALID", run, limit=100000, post=Mailer()))
check("a limit of zero is refused", raises("LIMIT_INVALID", run, limit=0, post=Mailer()))
st = A.status("launch-1")
check("status counts by state", st["sent"] == 4 and st["pending"] == 1, str(st))

# ---------------------------------------------------------------------------
print("\n[9] a test send touches nothing on the list")
fresh_list(2)
m = Mailer()
out = A.send_test("owner@example.com", SUBJECT, GOOD_BODY, CONTACT, post=m)
check("it sends exactly one email to the address given",
      [x["to"][0] for x in m.sent] == ["owner@example.com"] and out["status"] == "sent")
check("and marks the subject so nobody mistakes it for the real send",
      m.sent[0]["subject"].startswith("[TEST] "))
check("it records nothing on the list",
      all("announced" not in (_store._read(k) or {})
          for k in _store._set_members(W._k_index())))
check("a bad address is refused",
      raises("EMAIL_INVALID", A.send_test, "nope", SUBJECT, GOOD_BODY, CONTACT, post=m))

# ---------------------------------------------------------------------------
print("\n[9b] the logo has to be reachable before anybody gets the email")
fresh_list(2)
m = Mailer()
r = run(post=m, logo_check=lambda: False)
check("a dry run reports it and carries on", r["logoReachable"] is False and r["planned"] == 2)
check("a real send is refused when the logo does not answer",
      raises("LOGO_UNREACHABLE", run, send=True, confirm="SEND launch-1 TO 2",
             post=m, logo_check=lambda: False))
check("nothing went out", m.sent == [])
r = run(send=True, confirm="SEND launch-1 TO 2", post=m, text_only=True,
        logo_check=lambda: False)
check("--text-only needs no logo and sends text only",
      r["sent"] == 2 and all("html" not in x for x in m.sent) and r["format"] == "text")
fresh_list(2)
m = Mailer()
run(send=True, confirm="SEND launch-1 TO 2", post=m)
check("by default both parts go out", all("html" in x and "text" in x for x in m.sent))

# ---------------------------------------------------------------------------
print("\n[10] two runs at once")
fresh_list(2)
real_claim = A._claim_run
SEND = dict(send=True, confirm="SEND launch-1 TO 2")
A._claim_run = lambda campaign: False      # somebody else holds the lease
m = Mailer()
check("a real send that cannot take the lease is refused",
      raises("RUN_LOCKED", run, lock=True, post=m, **SEND))
A._claim_run = lambda campaign: None       # no shared backend: cannot ask
check("so is one that cannot ask who holds it",
      raises("LOCK_UNKNOWN", run, lock=True, post=m, **SEND))
check("neither sent anything", m.sent == [])
check("a dry run needs no lease", run(lock=True, post=m)["dryRun"] is True)
released = []
A._claim_run = lambda campaign: True
A._release_run = lambda campaign: released.append(campaign)
run(lock=True, post=m, **SEND)
check("a run that took the lease gives it back", released == ["launch-1"])
A._claim_run = real_claim

print("\n[11] the command line")
import contextlib                                         # noqa: E402
import importlib.util                                     # noqa: E402
import io                                                 # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "waitlist_announce_cli", os.path.join(ROOT, "scripts", "waitlist_announce.py"))
CLI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CLI)
_body = os.path.join(_TMP, "body.txt")
with open(_body, "w", encoding="utf-8") as fh:
    fh.write(GOOD_BODY)


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = CLI.main(list(argv))
    return code, out.getvalue(), err.getvalue()


base = ["--campaign", "launch-1", "--subject", SUBJECT, "--body-file", _body,
        "--remove-contact", CONTACT, "--no-lock"]
addrs = fresh_list(3)
mailer = Mailer()
A._post_resend = mailer
code, out, err = cli(*base)
check("a dry run exits 0 and says it sent nothing",
      code == 0 and "DRY RUN" in out and mailer.sent == [], out)
check("it prints the phrase to type", 'SEND launch-1 TO 3' in out)
check("and no whole address", not any(a in out + err for a in addrs))
code, out, err = cli(*base, "--send")
check("--send without the phrase is refused (exit 2), nothing sent",
      code == 2 and "CONFIRM_MISMATCH" in err and mailer.sent == [])
code, out, err = cli(*base, "--send", "--confirm", "SEND launch-1 TO 3")
check("with the phrase it sends and exits 0", code == 0 and len(mailer.sent) == 3, err)
code, out, err = cli("--campaign", "launch-1", "--status")
check("--status prints counts only",
      code == 0 and "sent 3" in out and not any(a in out for a in addrs), out)
code, out, err = cli("--campaign", "launch-1", "--subject", SUBJECT)
check("a missing body file is refused", code == 2, err)
code, out, err = cli("--campaign", "launch-1", "--subject", SUBJECT,
                     "--body-file", _body, "--no-lock")
check("a missing removal contact is refused, even on a dry run",
      code == 2 and "NO_REMOVE_CONTACT" in err, err)
code, out, err = cli(*base, "--text-only")
check("a dry run says which format it will send", code == 0 and "html+text" not in out
      and "format         : text" in out, out)
code, out, err = cli(*base)
check("and by default, that it is text plus HTML with the logo reachable",
      "html+text" in out and "logo reachable: yes" in out, out)
code, out, err = cli(*base, "--test-to", "owner@example.com")
check("--test-to without --send sends nothing", code == 0 and len(mailer.sent) == 3)
code, out, err = cli(*base, "--test-to", "owner@example.com", "--send")
check("--test-to --send sends one, to that address",
      code == 0 and len(mailer.sent) == 4 and mailer.sent[-1]["to"] == ["owner@example.com"]
      and "owner@example.com" not in out, out)

print()
if _fails:
    print(f"{len(_fails)} FAILED:")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All waitlist-announce checks passed.")
