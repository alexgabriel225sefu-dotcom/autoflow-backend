"""Where the trading loop tells a person something happened.

A message is written to the process log and, when the platform notification
store will take it, to the in-app notification centre. A failure to store
one never stops a loop: the trade already happened, and the log line remains.
"""
import logging

_log = logging.getLogger("apex.alerts")


def note(user_id, text):
    """One sentence for one account. Never raises."""
    line = " ".join(str(text or "").split())[:500]
    _log.info("user=%s %s", user_id, line)
    print(f"[Alert:{user_id}] {line}")
    _store(user_id, "Notice", line)
    return True


def alert(user_id, result):
    """The loop's alert callback. `result` is the dict the engine already built."""
    if not isinstance(result, dict):
        return note(user_id, result)
    try:
        from apex import control
        control.event_from_alert(user_id, result)
    except Exception:
        pass
    action = str(result.get("action") or "alert")
    text = str(result.get("text") or result.get("reason") or action)
    line = " ".join(text.split())[:500]
    _log.info("user=%s action=%s %s", user_id, action, line)
    print(f"[Alert:{user_id}] {action}: {line}")
    _store(user_id, action.replace("_", " ")[:80] or "Alert", line)
    return True


def _store(user_id, title, body):
    try:
        from apex.platform import notifications as notes
        notes.notify(str(user_id), type=notes.SYSTEM, title=str(title)[:200] or "Alert",
                     body=str(body or "")[:1000], level=notes.INFO)
    except Exception as exc:
        print(f"[Alert] not stored ({type(exc).__name__})")


def daily_note(user_id):
    """The day rolled over. The journal holds the refusals; nothing is pushed."""
    return note(user_id, "The trading day rolled over. Refusals are in the journal.")


def start_loop(user_id):
    from apex import user_loop
    if user_loop.is_running(user_id):
        return False
    return user_loop.start(user_id, alert_fn=alert)


def restart_loop(user_id):
    """Restart a running loop so it rebuilds its broker from the stored record."""
    from apex import user_loop
    if not user_loop.is_running(user_id):
        return False
    user_loop.stop(user_id)
    return user_loop.start(user_id, alert_fn=alert)
