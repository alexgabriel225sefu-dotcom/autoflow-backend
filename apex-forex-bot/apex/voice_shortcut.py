"""Build the Apple Shortcut file, so nobody has to assemble it by hand.

Assembling this in the Shortcuts editor takes eleven separate steps, and the
two that decide whether it works at all — the order of the actions, and which
action's output feeds which field — are exactly the two the editor makes
hardest. Adding an action drops it wherever the cursor happens to be, and
moving it needs a long-press that starts on the icon rather than the text.
Reported live: the request action ended up FIRST, so the shortcut asked the
server before asking the person.

A .shortcut file is a plist. Generating it removes every one of those steps.

WHY `Ask for Input` AND NOT `Dictate Text`. Run from Siri, `Ask for Input`
speaks its prompt aloud and listens for the answer — that is what makes this
a conversation rather than a form. `Dictate Text` is for a shortcut launched
by a button, and under Siri it competes with Siri's own microphone; live it
answered "I did not catch that" every time.

The variable wiring is the part a person cannot see and so cannot fix: each
action carries a UUID, and a field that consumes another action's output holds
an attachment naming that UUID, anchored at an object-replacement character in
an otherwise empty string. Get one wrong and the field silently reads as empty.
"""
import plistlib
import uuid

# U+FFFC. A field that holds a variable is a string of exactly this character,
# with the attachment pinned to range {0, 1}.
OBJ = "￼"

ASK = "is.workflow.actions.ask"
DOWNLOAD_URL = "is.workflow.actions.downloadurl"
GET_VALUE = "is.workflow.actions.getvalueforkey"
SHOW_RESULT = "is.workflow.actions.showresult"
SPEAK = "is.workflow.actions.speaktext"


def _uuid():
    return str(uuid.uuid4()).upper()


def _text(value):
    """A plain string parameter."""
    return {"Value": {"string": str(value)},
            "WFSerializationType": "WFTextTokenString"}


def _var(out_uuid, out_name):
    """A parameter that reads another action's output."""
    return {
        "Value": {
            "attachmentsByRange": {
                "{0, 1}": {"Type": "ActionOutput",
                           "OutputUUID": out_uuid,
                           "OutputName": out_name},
            },
            "string": OBJ,
        },
        "WFSerializationType": "WFTextTokenString",
    }


def _field(key, value_param):
    return {"WFItemType": 0, "WFKey": _text(key), "WFValue": value_param}


def build(url: str, token: str, prompt: str = "What do you want to know?") -> bytes:
    """The finished shortcut, as a .shortcut file's bytes."""
    ask_id, url_id, val_id = _uuid(), _uuid(), _uuid()

    actions = [
        # 1 — Siri speaks this and listens. The whole point.
        {"WFWorkflowActionIdentifier": ASK,
         "WFWorkflowActionParameters": {
             "UUID": ask_id,
             "WFAskActionPrompt": prompt,
             "WFInputType": "Text",
         }},
        # 2 — POST {"token": ..., "text": <what they said>}
        {"WFWorkflowActionIdentifier": DOWNLOAD_URL,
         "WFWorkflowActionParameters": {
             "UUID": url_id,
             "WFURL": url,
             "WFHTTPMethod": "POST",
             "WFHTTPBodyType": "JSON",
             "WFJSONValues": {
                 "Value": {"WFDictionaryFieldValueItems": [
                     _field("token", _text(token)),
                     _field("text", _var(ask_id, "Provided Input")),
                 ]},
                 "WFSerializationType": "WFDictionaryFieldValue",
             },
         }},
        # 3 — pull `reply` out of the JSON that came back
        {"WFWorkflowActionIdentifier": GET_VALUE,
         "WFWorkflowActionParameters": {
             "UUID": val_id,
             "WFDictionaryKey": "reply",
             "WFGetDictionaryValueType": "Value",
             "WFInput": _var(url_id, "Contents of URL"),
         }},
        # 4 — on screen, so a muted phone still shows the answer
        {"WFWorkflowActionIdentifier": SHOW_RESULT,
         "WFWorkflowActionParameters": {
             "Text": _var(val_id, "Dictionary Value"),
         }},
        # 5 — and out loud
        {"WFWorkflowActionIdentifier": SPEAK,
         "WFWorkflowActionParameters": {
             "WFText": _var(val_id, "Dictionary Value"),
         }},
    ]

    workflow = {
        "WFWorkflowClientVersion": "1200.2",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconGlyphNumber": 59511,
            "WFWorkflowIconStartColor": 4282601983,
        },
        "WFWorkflowImportQuestions": [],
        "WFWorkflowTypes": ["NCWidget", "WatchKit"],
        "WFWorkflowInputContentItemClasses": [
            "WFAppStoreAppContentItem", "WFArticleContentItem",
            "WFContactContentItem", "WFDateContentItem",
            "WFEmailAddressContentItem", "WFGenericFileContentItem",
            "WFImageContentItem", "WFiTunesProductContentItem",
            "WFLocationContentItem", "WFDCMapsLinkContentItem",
            "WFAVAssetContentItem", "WFPDFContentItem",
            "WFPhoneNumberContentItem", "WFRichTextContentItem",
            "WFSafariWebPageContentItem", "WFStringContentItem",
            "WFURLContentItem",
        ],
        "WFWorkflowActions": actions,
    }
    return plistlib.dumps(workflow, fmt=plistlib.FMT_XML)
