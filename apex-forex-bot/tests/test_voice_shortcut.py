"""The shortcut is built and handed over, not assembled by hand.

Building it in the Shortcuts editor is eleven steps, and the two that decide
whether it works at all are the two the editor makes hardest: the ORDER of the
actions, and which action's output feeds which field. Both went wrong live —
the request action ended up first, so the shortcut asked the server before
asking the person, and a field that should have held a variable held the JSON
of a previous response instead.

Neither is visible to whoever is holding the phone. So this file pins them.

Run: python tests/test_voice_shortcut.py
"""
import os
import plistlib
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-vsc-")
os.environ["RENDER_EXTERNAL_URL"] = "https://example.invalid"

from apex import voice_shortcut, voice_api, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


URL = "https://example.invalid/api/voice"
TOKEN = "500.s3cr3t-value"
raw = voice_shortcut.build(URL, TOKEN, prompt="What do you want to know?")
wf = plistlib.loads(raw)
acts = wf["WFWorkflowActions"]
ids = [a["WFWorkflowActionIdentifier"] for a in acts]
P = [a["WFWorkflowActionParameters"] for a in acts]

print("\n🧪 VOICE SHORTCUT — built right, so nobody has to build it\n")

print("1. It is a shortcut iOS can read")
check("the file parses as a plist", isinstance(wf, dict))
check("it declares actions", len(acts) == 5, ids)

print("\n2. The order — asking must come before sending")
check("asking is FIRST", ids[0] == voice_shortcut.ASK, ids)
check("the request is second", ids[1] == voice_shortcut.DOWNLOAD_URL, ids)
check("then the reply is pulled out", ids[2] == voice_shortcut.GET_VALUE, ids)
check("shown, then spoken", ids[3:] == [voice_shortcut.SHOW_RESULT,
                                        voice_shortcut.SPEAK], ids[3:])

print("\n3. Ask for Input, not Dictate Text")
# Run from Siri, Ask for Input speaks its prompt and listens — that is what
# makes this a conversation. Dictate Text is for a button press, and under
# Siri it competes with Siri's own microphone: live it answered "I did not
# catch that" every single time.
check("no Dictate Text anywhere", "is.workflow.actions.dictatetext" not in ids)
check("the prompt is set", P[0].get("WFAskActionPrompt"))
check("it asks for text", P[0].get("WFInputType") == "Text")

print("\n4. The request itself")
check("it posts", P[1].get("WFHTTPMethod") == "POST",
      "a GET reaches the endpoint and is refused")
check("as JSON", P[1].get("WFHTTPBodyType") == "JSON")
check("to the voice endpoint", P[1].get("WFURL") == URL)
fields = P[1]["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]
by_key = {f["WFKey"]["Value"]["string"]: f["WFValue"] for f in fields}
check("it sends exactly token and text", set(by_key) == {"token", "text"}, list(by_key))
check("the key is embedded literally",
      by_key["token"]["Value"]["string"] == TOKEN)

print("\n5. The wiring nobody can see, and so nobody can fix")
ask_uuid = P[0]["UUID"]
url_uuid = P[1]["UUID"]
val_uuid = P[2]["UUID"]


def linked_to(param):
    att = param["Value"].get("attachmentsByRange", {}).get("{0, 1}")
    return att and att.get("OutputUUID")


check("what was said is what gets sent",
      linked_to(by_key["text"]) == ask_uuid,
      "the text field must carry the answer, not a typed string")
check("the reply is read from THIS request's response",
      linked_to(P[2]["WFInput"]) == url_uuid)
check("and it reads the `reply` key", P[2].get("WFDictionaryKey") == "reply")
check("what is shown is that value", linked_to(P[3]["Text"]) == val_uuid)
check("and what is spoken is the same value", linked_to(P[4]["WFText"]) == val_uuid)
check("every action has its own identity",
      len({ask_uuid, url_uuid, val_uuid}) == 3)
check("a variable field is anchored on the object-replacement character",
      by_key["text"]["Value"]["string"] == voice_shortcut.OBJ,
      "iOS reads the attachment at range {0, 1}; any other string breaks it")

print("\n6. Two builds are two different shortcuts, not the same one twice")
other = plistlib.loads(voice_shortcut.build(URL, TOKEN))
check("identities are freshly generated",
      other["WFWorkflowActions"][0]["WFWorkflowActionParameters"]["UUID"] != ask_uuid)

print("\n7. The download link carries a code, never the key")
# A key in a query string is a key in every request log between the server and
# the phone. The code names an account and is worth nothing on its own.
user_store.update("500", {"active": True})
code = voice_api.mint_download("500")
check("the code is not the key", "." not in code and len(code) > 8, code)
check("it resolves to its account", voice_api.redeem_download(code) == "500")
check("and only once", voice_api.redeem_download(code) is None,
      "a download link must not be replayable")
check("an unknown code resolves to nobody",
      voice_api.redeem_download("made-up") is None)
check("so does an empty one", voice_api.redeem_download("") is None
      and voice_api.redeem_download(None) is None)

print("\n8. Wired into the bot and the Telegram command")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
TG = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
BRANCH = BOT.split('self.path.startswith("/voice/shortcut")')[1].split(
    'if self.path.startswith("/api/voice")')[0]
check("the route exists", 'self.path.startswith("/voice/shortcut")' in BOT)
check("it authenticates with the one-time code",
      "voice_api.redeem_download(code)" in BRANCH)
check("a spent code is refused, not served", "410" in BRANCH)
check("the key is minted at download, so it never travels in the link",
      "voice_api.mint(uid)" in BRANCH)
check("it is served as a shortcut file",
      "application/x-shortcut" in BRANCH)
check("named Apex, which is what Siri will listen for",
      'filename="Apex.shortcut"' in BRANCH,
      "the shortcut takes its name from the filename")
check("/voice new hands over a link", "voice_api.mint_download(chat_id)" in TG)
check("and no longer walks anyone through the editor",
      "Add Shortcut" in TG and "Add new field" not in TG)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the shortcut arrives built.")
