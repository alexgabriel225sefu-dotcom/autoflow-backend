# NOVA Shortcuts — the part that touches your phone

The gateway thinks. **Shortcuts act.** That split is not a design preference,
it is what iOS allows: the OpenClaw iOS app has *"no local system integration
(Contacts, Messages, Phone), no direct Siri/Shortcuts support"*. Shortcuts has
all of it.

## You have to build these by hand

Unsigned `.shortcut` files cannot be imported on iOS — Apple refuses them.
There is no file anyone can hand you, and a link claiming otherwise is either
signed by Apple or will not open. Each shortcut below is a handful of taps,
once.

Everything is in the **Shortcuts** app → **+** → **Add Action**.

---

## 1. "NOVA" — the main one

Ask NOVA anything by voice, hear the answer.

| # | Action | Set it to |
|---|---|---|
| 1 | **Dictate Text** | Stop listening: *After Pause* |
| 2 | **Get Contents of URL** | URL: your gateway endpoint (NOVA_SETUP.md §9) |
| | | Method: **POST** |
| | | Headers: `Authorization` → `Bearer <OPENCLAW_GATEWAY_TOKEN>` |
| | | Request Body: **JSON**, field `text` → *Dictated Text* |
| 3 | **Speak Text** | Input: the reply field from step 2 |

Rename it **NOVA**. Then: *"Hey Siri, NOVA"* → it listens → it answers aloud.

**The name is the trigger.** Siri runs a shortcut by its exact name, so keep it
short and distinct. "NOVA" works; "Talk to NOVA assistant" is worse.

---

## 2. "NOVA Call" — phone a contact

| # | Action | Notes |
|---|---|---|
| 1 | **Dictate Text** | say the name |
| 2 | **Find Contacts** where *Name* **contains** *Dictated Text* | |
| 3 | **If** *Count* **is** `1` → **Call** | |
| 4 | **Otherwise** → **Choose from List** → **Call** | two Alexes means it asks which |

Step 4 is the ambiguity handling the brief asks for. iOS may also show its own
confirmation before dialling — that is the system asking, and it is not
something to work around.

---

## 3. "NOVA Open" — launch an app

| # | Action |
|---|---|
| 1 | **Dictate Text** |
| 2 | **If** it contains `Telegram` → **Open App** → Telegram |
| 3 | Repeat the If-branch per app you care about |

`Open App` reaches apps installed on the phone. It opens them; it cannot drive
their interface, and iOS provides no way to.

---

## 4. "NOVA Message" — send a message

| # | Action | Notes |
|---|---|---|
| 1 | **Dictate Text** — the recipient | |
| 2 | **Find Contacts** → resolve as in *NOVA Call* | |
| 3 | **Dictate Text** — the message | |
| 4 | **Show Alert** with the message text | **Keep this** — it is the confirmation gate |
| 5 | **Send Message** to the contact | |

Step 4 is deliberate. Without it, a misheard word gets sent to a real person.

---

## Why not one shortcut for everything

Siri matches on the name. A single shortcut called "NOVA" that then has to work
out whether you meant *call*, *open* or *ask* adds a branch that can misfire on
a misheard word — and a misfire here dials somebody. Separate names, separate
intents, no guessing.

## What Shortcuts cannot do

- Run without you triggering it. There is no always-listening wake word for a
  third party; only Apple's own "Hey Siri" is a system-level trigger.
- Read other apps' notifications.
- Control another app's interface.
- Run reliably in the background for long stretches.
