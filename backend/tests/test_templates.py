# ruff: noqa: E501
"""Every shipped workflow template really runs.

The two steps that need the outside world (HTTP and Claude) are swapped for canned answers; everything
else, including every file read and write, is the real thing against a throw-away files folder.
"""

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.nodes.builtin.data_nodes import render_template
from app.nodes.builtin.http_request import HttpRequestNode, render_url
from tests.test_run_events import start_run
from tests.test_storage_api import wait_run


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(data_dir=tmp_path / "data", secret_backend="memory")
    with TestClient(create_app(f"sqlite:///{tmp_path / 't.db'}", settings)) as c:
        yield c


def files_dir(c: TestClient) -> Path:
    return Path(c.get("/api/v1/files").json()["folder"])


def stub(output: Any) -> dict[str, Any]:
    return {"source": f"def main(input_data):\n    return {output!r}\n"}


def build(c: TestClient, example_id: str, canned: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Create the example (which adds its sample files), then a copy with canned outside-world steps."""
    made = c.post(f"/api/v1/examples/{example_id}/create")
    assert made.status_code == 201, made.text
    original = c.get(f"/api/v1/workflows/{made.json()['id']}").json()["draft"]
    nodes = []
    for n in original["nodes"]:
        if n["id"] in canned:
            n = {**n, "type": "code.python", "config": stub(canned[n["id"]])}
        nodes.append(n)
    copy = c.post(
        "/api/v1/workflows", json={"name": "t", "definition": {**original, "nodes": nodes}}
    )
    assert copy.status_code == 201, copy.text
    return copy.json()["id"], original


def run(c: TestClient, wid: str, run_input: Any = None) -> dict[str, dict[str, Any]]:
    result = wait_run(c, start_run(c, wid, input=run_input))
    return {n["node_id"]: n for n in result["nodes"]}


def prompt_renders_fully(original: dict[str, Any], node_id: str, executed: dict[str, Any]) -> None:
    """The real Claude node would fill every {{ $.x }} placeholder from what actually reached it."""
    cfg = next(n for n in original["nodes"] if n["id"] == node_id)["config"]
    render_template(cfg["prompt"], executed[node_id]["input"], escape=False, strict=True)


def test_every_template_validates_and_is_listed(client: TestClient) -> None:
    listing = {e["id"]: e for e in client.get("/api/v1/examples").json()}
    assert {
        "debug-me", "route-orders", "github-daily-report", "bug-triage", "study-flashcards",
        "habit-tracker", "habit-weekly-stats", "backup-report", "csv-cleaner", "repo-brief",
        "article-digest",
    } <= set(listing)  # fmt: skip
    for e in listing.values():
        assert len(e["description"]) > 40


# ---------------------------------------------------------------------------------- GitHub report
def test_github_daily_report(client: TestClient) -> None:
    items = {
        "items": [
            {"repository_url": "https://api.github.com/repos/o/r", "number": 7, "title": "Fix crash",
             "user": {"login": "ana"}, "state": "open", "labels": [{"name": "bug"}], "pull_request": {}},
            {"repository_url": "https://api.github.com/repos/o/r", "number": 8, "title": "Add docs",
             "user": {"login": "ben"}, "state": "open", "labels": []},
        ]
    }  # fmt: skip
    wid, original = build(
        client, "github-daily-report",
        {"fetch": {"status": 200, "body": items}, "summarize": {"text": "Needs action today\n- o/r#7"}},
    )  # fmt: skip
    ran = run(client, wid, {"repos": ["o/r", "o/s"]})
    assert ran["repos"]["output"]["q"].startswith("repo:o/r repo:o/s updated:>=")
    digest = ran["shape"]["output"]["digest"]
    assert (
        "[PR] o/r#7 Fix crash (by ana, open, labels: bug)" in digest and "[issue] o/r#8" in digest
    )
    assert ran["quiet"]["status"] == "skipped"
    prompt_renders_fully(original, "summarize", ran)
    saved = (files_dir(client) / "reports/github-daily.md").read_text()
    assert "Needs action today" in saved and saved.startswith("## 20")
    # the real URL: the query is filled in, percent-encoded, and the host is untouched
    url = next(n for n in original["nodes"] if n["id"] == "fetch")["config"]["url"]
    assert render_url(url, ran["repos"]["output"]).startswith(
        "https://api.github.com/search/issues?q=repo%3Ao%2Fr%20repo%3Ao%2Fs"
    )
    assert (
        HttpRequestNode().validate_config(
            next(n for n in original["nodes"] if n["id"] == "fetch")["config"]
        )
        == []
    )


def test_github_report_on_a_quiet_day(client: TestClient) -> None:
    wid, _ = build(client, "github-daily-report", {"fetch": {"status": 200, "body": {"items": []}}})
    ran = run(client, wid)
    assert (
        ran["summarize"]["status"] == "skipped"
    )  # Claude is not asked (or paid) to summarize nothing
    assert "Nothing was updated" in (files_dir(client) / "reports/github-daily.md").read_text()


# ---------------------------------------------------------------------------------- bug triage
def test_bug_triage_urgent_and_routine(client: TestClient) -> None:
    wid, original = build(
        client, "bug-triage", {"analyze": {"text": "Likely cause: a null save handler."}}
    )
    urgent = run(client, wid)  # the built-in sample mentions a crash
    assert (
        urgent["report"]["output"]["urgent"] is True
        and "crash" in urgent["report"]["output"]["signals"]
    )
    assert urgent["analyze"]["status"] == "succeeded" and urgent["routine"]["status"] == "skipped"
    prompt_renders_fully(original, "analyze", urgent)
    routine = run(client, wid, {"title": "Typo on the docs page", "body": "teh", "reporter": "kim"})
    assert routine["analyze"]["status"] == "skipped" and routine["routine"]["status"] == "succeeded"
    log = (files_dir(client) / "triage/bugs.md").read_text()
    assert "[URGENT] App crashes" in log and "[routine] Typo on the docs page" in log
    assert "Reported by kim" in log and "null save handler" in log


# ---------------------------------------------------------------------------------- flashcards
def test_flashcards_clean_up_claudes_reply(client: TestClient) -> None:
    reply = '```csv\nquestion,answer\nWhat makes ATP?,"Mitochondria, mostly"\nwhat makes atp?,duplicate\n,empty\nWhat stores DNA?,The nucleus\n```'
    wid, original = build(client, "study-flashcards", {"cards": {"text": reply}})
    ran = run(client, wid)
    assert ran["notes"]["output"]["text"].startswith("Cell biology")  # the sample notes were added
    prompt_renders_fully(original, "cards", ran)
    assert ran["clean"]["output"]["count"] == 2
    cards = (files_dir(client) / "study/flashcards.csv").read_text()
    assert (
        cards
        == 'question,answer\nWhat makes ATP?,"Mitochondria, mostly"\nWhat stores DNA?,The nucleus\n'
    )


def test_flashcards_say_so_when_claude_returns_nothing_usable(client: TestClient) -> None:
    wid, _ = build(client, "study-flashcards", {"cards": {"text": "Sorry, I cannot do that."}})
    ran = run(client, wid)
    assert (
        ran["clean"]["status"] == "failed"
        and "not the flashcard CSV" in ran["clean"]["error"]["message"]
    )
    assert ran["save"]["status"] == "skipped"


# ---------------------------------------------------------------------------------- habits
def test_habit_tracker_and_weekly_stats(client: TestClient) -> None:
    track, _ = build(client, "habit-tracker", {})
    stats, _ = build(client, "habit-weekly-stats", {})
    assert (
        run(client, stats)["stats"]["output"]["habits"] == 0
    )  # no log yet: a friendly empty report
    run(client, track, {"habit": "Walk", "value": 30, "note": "morning, quick"})
    run(client, track, {"habit": "walk", "value": 20})
    run(client, track)  # the sample entry
    bad = run(client, track, {"habit": "run", "value": "lots"})
    assert bad["entry"]["status"] == "failed" and "number" in bad["entry"]["error"]["message"]
    assert (files_dir(client) / "habits/log.csv").read_text().count("\n") == 3
    out = run(client, stats)["stats"]["output"]
    assert out["habits"] == 1
    assert "| walk | 1/7 | 80 | 1 |" in out["text"]  # 30 + 20 + 30 on today, one streak day
    assert (files_dir(client) / "habits/weekly.md").read_text().startswith("# Habits this week")


# ---------------------------------------------------------------------------------- backups
def test_backup_report_tracks_changes_between_runs(client: TestClient) -> None:
    wid, _ = build(client, "backup-report", {})
    first = run(client, wid)["report"]["output"]["text"]
    assert "First run: everything counts as new." in first and "1 files" in first
    (files_dir(client) / "backups/db-monday.sql").write_text("select 1;")
    (files_dir(client) / "backups/empty.sql").write_text("")
    second = run(client, wid)["report"]["output"]["text"]
    assert "2 new, 0 changed, 0 missing" in second and "1 empty file(s)" in second
    (files_dir(client) / "backups/db-monday.sql").write_text("select 1; select 2;")
    (files_dir(client) / "backups/README.txt").unlink()
    third = run(client, wid)["report"]["output"]["text"]
    assert "0 new, 1 changed, 1 missing" in third and "backups/README.txt" in third
    assert "reports/" not in json.loads(
        (files_dir(client) / "reports/backup-manifest.json").read_text()
    )


# ---------------------------------------------------------------------------------- csv cleaner
def test_csv_cleaner_on_the_sample(client: TestClient) -> None:
    wid, _ = build(client, "csv-cleaner", {})
    ran = run(client, wid)
    assert ran["clean"]["status"] == "succeeded", ran["clean"]
    clean = (files_dir(client) / "inbox/clean.csv").read_text().splitlines()
    assert clean[0] == "customer_name,signup_date,amount_paid,notes"
    assert clean[1:] == [
        "Ana Lopez,2026-04-03,1200.5,vip",
        "ben carter,2026-04-05,99,",
        "Chloe Ng,2026-04-12,45.0,new",
        "Dev Patel,2026-04-20,3050,",
    ]
    report = (files_dir(client) / "inbox/clean-report.md").read_text()
    assert "7 rows in, 4 rows out" in report or "6 rows in, 4 rows out" in report
    assert "1 duplicate row(s) removed" in report and "signup_date read as date" in report
    assert "amount_paid read as number" in report


# ---------------------------------------------------------------------------------- repo brief
def test_repo_brief(client: TestClient) -> None:
    readme = base64.encodebytes(b"# Click\nA command line toolkit.\n").decode()
    info = {"full_name": "pallets/click", "description": "CLI toolkit", "language": "Python",
            "stargazers_count": 1, "open_issues_count": 2, "topics": ["cli"], "license": {"name": "BSD"},
            "default_branch": "main"}  # fmt: skip
    wid, original = build(
        client, "repo-brief",
        {"info": {"status": 200, "body": info}, "readme": {"status": 200, "body": {"content": readme}},
         "explain": {"text": "It builds CLIs."}},
    )  # fmt: skip
    ran = run(client, wid, {"repo": "https://github.com/pallets/click/"})
    assert ran["target"]["output"] == {"repo": "pallets/click"}
    assert "command line toolkit" in ran["compose"]["output"]["facts"]
    prompt_renders_fully(original, "explain", ran)
    saved = (files_dir(client) / "briefs/repo-briefs.md").read_text()
    assert "## pallets/click" in saved and "It builds CLIs." in saved
    bad = run(client, wid, {"repo": "not a repo"})
    assert bad["target"]["status"] == "failed" and "owner/name" in bad["target"]["error"]["message"]
    for nid in ("info", "readme"):
        cfg = next(n for n in original["nodes"] if n["id"] == nid)["config"]
        assert HttpRequestNode().validate_config(cfg) == []


# ---------------------------------------------------------------------------------- digest
def test_reading_digest(client: TestClient) -> None:
    rss = ('<?xml version="1.0"?><rss><channel><item><title>Python 4 rumours</title><link>https://e.com/1</link>'
           "<description>&lt;p&gt;All about &lt;b&gt;Python&lt;/b&gt;&lt;/p&gt;</description></item>"
           "<item><title>Cats</title><link>https://e.com/2</link></item></channel></rss>")  # fmt: skip
    wid, original = build(
        client, "article-digest", {"feed": {"status": 200, "body": rss}, "pick": {"text": "1. Python 4 rumours"}}
    )  # fmt: skip
    ran = run(client, wid)
    listing = ran["parse"]["output"]["list"]
    assert (
        "- Python 4 rumours (https://e.com/1) All about Python" in listing
        and "- Cats (https://e.com/2)" in listing
    )
    prompt_renders_fully(original, "pick", ran)
    assert "Python 4 rumours" in (files_dir(client) / "reading/digest.md").read_text()
    not_a_feed = build(
        client, "article-digest", {"feed": {"status": 200, "body": "<html><body>hi</body></html>"}}
    )[0]
    assert "No entries found" in run(client, not_a_feed)["parse"]["error"]["message"]


def test_creating_an_example_never_overwrites_your_own_files(client: TestClient) -> None:
    client.put("/api/v1/files/content", json={"path": "study/notes.txt", "text": "MY OWN NOTES"})
    client.post("/api/v1/examples/study-flashcards/create")
    assert (files_dir(client) / "study/notes.txt").read_text() == "MY OWN NOTES"
