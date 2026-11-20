# NOVA — what iOS actually allows

Every line here was read from official documentation, not inferred. Where a
capability is absent, the absence is stated rather than papered over.

**The single constraint that shapes everything:** you have an iPhone and no
Mac. Xcode is macOS-only, so a custom "NOVA" iOS app cannot be built or
installed by you. NOVA therefore runs on three clients that already exist:
Telegram, Shortcuts, and OpenClaw's own iOS app.

---

## The capability matrix

### ✅ SUPPORTED

| Capability | Through | Source |
|---|---|---|
| Natural conversation with context | Telegram channel | OpenClaw channels |
| Web search and page fetch | `group:web` — `web_search`, `x_search`, `web_fetch` | OpenClaw tool groups |
| Persistent memory | `group:memory` on the persistent disk | OpenClaw |
| Speak a request, hear the answer | Shortcuts: Dictate Text → Get Contents of URL → Speak Text | Apple Shortcuts |
| "Hey Siri, NOVA" | Siri runs a shortcut by name | Apple |
| Place a call | Shortcuts: Find Contacts → Call | Apple Shortcuts |
| Send a message | Shortcuts: Send Message | Apple Shortcuts |
| Open an installed app | Shortcuts: Open App / URL schemes | Apple Shortcuts |
| Reminders, calendar | Shortcuts | Apple Shortcuts |
| Contacts lookup, ambiguity handling | Shortcuts: Find Contacts + Choose from List | Apple Shortcuts |
| Tool permission levels | `tools.profile` + allow/deny + tool groups | OpenClaw |

### 🟡 PARTIALLY SUPPORTED — foreground only

| Capability | The exact limit |
|---|---|
| Camera / "what am I looking at?" | The OpenClaw app exposes camera capture, but *"Camera and screen commands require the iOS app in the foreground."* |
| Voice wake | *"iOS may suspend background audio; treat voice features as best-effort when the app is not active."* |
| Talk mode | Same suspension applies |
| Screen snapshot, location | Foreground only |
| Security Mode | See below — it is real, but only with the app open |

### ❌ NOT SUPPORTED — and no safe workaround exists

| Capability | Why |
|---|---|
| **Reading other apps' notifications** | Apple exposes no API and no entitlement for it to third-party apps. Not a configuration gap — a platform decision. Android's `NotificationListenerService` does allow it; iOS has no equivalent. |
| **Always-listening wake word in the background** | iOS suspends background audio. Only Apple's own "Hey Siri" runs at system level. |
| **The OpenClaw app placing calls, sending messages, or reading Contacts** | Documented directly: *"No local system integration (Contacts, Messages, Phone), no direct Siri/Shortcuts support, no third-party app launching documented."* This is why Shortcuts carries those jobs. |
| **Driving another app's interface** | iOS provides no automation surface for it. |
| **A custom NOVA iOS app** | Requires a Mac with Xcode. |
| **macOS integrations (Notes, Reminders app)** | Render's own OpenClaw page: *"some capabilities of OpenClaw expect a macOS environment… not supported on Render."* |

---

## Security Mode, honestly

**What was asked:** the phone watches, detects a person, and speaks a warning.

**What iOS permits:** exactly that — with the app in the foreground, the screen
on, and the camera indicator visible. There is no background camera access for
third-party apps, and the indicator cannot be suppressed.

**So the safe version is:** phone propped up, NOVA open in Security Mode,
**presence detection** (not facial recognition), configurable spoken response.

That is a visible deterrent, not covert surveillance. The difference is not
cosmetic — hidden camera use is what the platform forbids, and what the brief
correctly rules out. Face recognition for identifying a specific person is left
out deliberately: it needs a legal basis, and presence detection answers the
actual question ("someone picked up my phone") without one.

**What it cannot be:** a security system that runs while the phone is locked in
your pocket. Nothing on iOS can be.

---

## The notification question, in full

This is the capability most often promised and least often possible.

- **iOS:** an app cannot read notifications belonging to other apps. There is
  no entitlement to request, no permission the user can grant, and no
  App Store-compatible technique. The OpenClaw iOS app can *send* a
  notification (`system.notify`) while active; it cannot read yours.
- **Android:** `NotificationListenerService` does exactly what was asked. It is
  gated behind a permission granted by hand in Settings → Notifications →
  Notification access; it cannot be granted programmatically, and Play Store
  distribution of such apps is restricted.

If notification triage matters more than the rest, that is an argument for an
Android device — a hardware decision, not something configuration can solve.

**The nearest safe alternative on iOS:** have the *sources* push to NOVA
instead of reading the phone's notification tray. Email, GitHub and APEX can
all notify the gateway directly, and NOVA can then decide what is worth your
attention. That covers most of the real intent without touching the sandbox.

---

## Two paths, and why both exist

| | Telegram | Shortcuts |
|---|---|---|
| Works with phone locked | ✅ | ❌ |
| Works with app closed | ✅ | ✅ (Siri) |
| Conversation with context | ✅ | one turn at a time |
| Can call / message / open apps | ❌ | ✅ |
| Hands-free | ❌ | ✅ |

Neither is sufficient alone. Telegram is the reliable brain; Shortcuts is the
hands. The OpenClaw iOS node adds eyes — but only while you are looking at it.
