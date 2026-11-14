"""The trader's own tags and comment on a journal entry.

A journal entry is evidence and is never edited. A note lives beside it under
its own key, owned by the same client, so annotating an entry can neither alter
what the platform recorded nor be mistaken for it. A note on an entry that is
not the caller's, or does not exist, is refused as "no such entry".
"""
import re
import time

from apex.platform import journal_store as _js
from apex.platform import store as _store

MAX_TAGS = 8
MAX_TAG_LEN = 24
MAX_COMMENT = 2000
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,%d}$" % (MAX_TAG_LEN - 1))


class NoteInvalid(ValueError):
    pass


def _k(owner, entry_id):
    return f"{_store._ns()}:{_store._P}:jnote:{owner}:{entry_id}"


def clean(tags, comment):
    """Validated (tags, comment), or NoteInvalid. Nothing is silently trimmed
    except surrounding whitespace and duplicate tags."""
    if tags is None:
        tags = []
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise NoteInvalid("tags must be a list of text")
    out = []
    for t in tags:
        t = t.strip()
        if not t:
            continue
        if not _TAG_RE.match(t):
            raise NoteInvalid(
                f"a tag may use letters, numbers, spaces, - and _ "
                f"(up to {MAX_TAG_LEN} characters)")
        if t.lower() not in [x.lower() for x in out]:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise NoteInvalid(f"at most {MAX_TAGS} tags")
    if comment is None:
        comment = ""
    if not isinstance(comment, str):
        raise NoteInvalid("comment must be text")
    comment = comment.strip()
    if len(comment) > MAX_COMMENT:
        raise NoteInvalid(f"a comment may be up to {MAX_COMMENT} characters")
    return out, comment


def get(owner_id, entry_id):
    """The note, or None when there is none. Raises JournalNotFound if the
    entry itself is not this owner's."""
    owner = str(owner_id)
    _js.get(owner, entry_id)
    row = _store._read(_k(owner, str(entry_id)))
    if not isinstance(row, dict) or str(row.get("userId")) != owner:
        return None
    return {"tags": row.get("tags") or [], "comment": row.get("comment") or "",
            "updatedAt": row.get("updatedAt")}


def put(owner_id, entry_id, tags, comment, *, now=None):
    owner = str(owner_id)
    _js.get(owner, entry_id)                 # ownership and existence first
    t, c = clean(tags, comment)
    if not t and not c:
        _store._write(_k(owner, str(entry_id)), None)
        return None
    row = {"userId": owner, "entryId": str(entry_id), "tags": t, "comment": c,
           "updatedAt": time.time() if now is None else now}
    _store._write(_k(owner, str(entry_id)), row)
    return {"tags": t, "comment": c, "updatedAt": row["updatedAt"]}
