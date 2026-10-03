from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web" / "src"
DOCS = ROOT / "docs"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_all(text: str, needles: list[str], path: Path) -> None:
    missing = [needle for needle in needles if needle not in text]
    assert not missing, f"{path} is missing {missing!r}"


def test_ctrader_browser_walkthrough_checklist_is_documented():
    doc = read(DOCS / "CTRADER_DEMO_SMOKE_TEST.md")

    assert_all(
        doc,
        [
            "Sign up",
            "Connect",
            "Select",
            "DEMO",
            "balance, positions, orders",
            "chart",
            "Build a rule",
            "preview",
            "Activate",
            "start",
            "Pause, resume, stop",
            "Disconnect",
            "phone",
        ],
        DOCS / "CTRADER_DEMO_SMOKE_TEST.md",
    )
    assert "full account number" in doc
    assert "token" in doc


def test_connected_ctrader_ui_exposes_the_manual_walkthrough_states():
    dashboard = read(WEB / "app" / "(app)" / "dashboard" / "page.tsx")
    accounts = read(WEB / "app" / "(app)" / "accounts" / "page.tsx")
    connect = read(WEB / "app" / "(app)" / "connect" / "page.tsx")
    market = read(WEB / "components" / "chart" / "market-panel.tsx")
    rules = read(WEB / "app" / "(app)" / "rules" / "page.tsx")
    rule_new = read(WEB / "app" / "(app)" / "rules" / "new" / "page.tsx")
    rule_detail = read(WEB / "app" / "(app)" / "rules" / "[id]" / "page.tsx")
    journal = read(WEB / "app" / "(app)" / "journal" / "page.tsx")

    # OAuth/connect must have an observable no-request path and a safe operator reference.
    assert_all(
        connect,
        [
            "NO_PENDING",
            "diagnosticId",
            "Reference:",
            "Choose which one to trade",
            "Connect another account",
        ],
        WEB / "app" / "(app)" / "connect" / "page.tsx",
    )

    # Account selection must expose demo/live mode, block live accounts, and offer disconnect.
    assert_all(
        accounts,
        [
            "StatusPill mode={a.mode}",
            "Live accounts are not available here.",
            "Select this account",
            "Disconnect cTrader",
        ],
        WEB / "app" / "(app)" / "accounts" / "page.tsx",
    )

    # The dashboard must render the server execution verdict and all demo controls.
    assert_all(
        dashboard,
        [
            "ExecutionBadge",
            "me.result.data.execution",
            "control(\"start\")",
            "control(\"pause\")",
            "control(\"resume\")",
            "control(\"stop\")",
            "MarketPanel",
            "positions",
            "orders",
            "journal",
        ],
        WEB / "app" / "(app)" / "dashboard" / "page.tsx",
    )

    # The chart must show evidence that can be compared to cTrader itself.
    assert_all(
        market,
        [
            "read.count",
            "latest bar",
            "The broker answered with no bars",
            "status",
            "reason",
        ],
        WEB / "components" / "chart" / "market-panel.tsx",
    )

    # The rule and journal screens must make preview and no-trade evaluations visible.
    assert_all(
        rules,
        ["New rule", "Create one to get started."],
        WEB / "app" / "(app)" / "rules" / "page.tsx",
    )
    assert_all(
        rule_new,
        ["New rule", "Validate it", "Preview it against real bars"],
        WEB / "app" / "(app)" / "rules" / "new" / "page.tsx",
    )
    assert_all(
        rule_detail,
        ["Preview a decision", "Preview", "This preview placed nothing", "rules/${id}/preview"],
        WEB / "app" / "(app)" / "rules" / "[id]" / "page.tsx",
    )
    assert_all(
        journal,
        [
            "Every evaluation",
            "No order placed",
            "automation_paused",
            "automation_stopped",
        ],
        WEB / "app" / "(app)" / "journal" / "page.tsx",
    )


def test_mobile_first_routes_needed_for_ctrader_demo_beta_exist():
    route_files = [
        WEB / "app" / "(app)" / "dashboard" / "page.tsx",
        WEB / "app" / "(app)" / "connect" / "page.tsx",
        WEB / "app" / "(app)" / "accounts" / "page.tsx",
        WEB / "app" / "(app)" / "rules" / "page.tsx",
        WEB / "app" / "(app)" / "positions" / "page.tsx",
        WEB / "app" / "(app)" / "journal" / "page.tsx",
    ]
    missing = [str(path.relative_to(ROOT)) for path in route_files if not path.exists()]
    assert not missing, f"Missing beta walkthrough routes: {missing!r}"

if __name__ == "__main__":
    tests = [
        test_ctrader_browser_walkthrough_checklist_is_documented,
        test_connected_ctrader_ui_exposes_the_manual_walkthrough_states,
        test_mobile_first_routes_needed_for_ctrader_demo_beta_exist,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print("all cTrader browser walkthrough contract checks passed")


