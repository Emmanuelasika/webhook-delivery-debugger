from html.parser import HTMLParser
from pathlib import Path


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if tag in {"a", "link"}:
            self.links.append(attributes.get("href", ""))


def test_pages_site_has_complete_navigation_and_assets():
    root = Path(__file__).parents[1]
    parser = PageParser()
    parser.feed((root / "docs/index.html").read_text(encoding="utf-8"))
    assert {"top", "investigation", "failure-lab", "architecture", "ledger"} <= parser.ids
    assert "site.css" in parser.links
    assert (root / "docs/site.css").stat().st_size > 5_000


def test_pages_site_contains_working_case_study_controls():
    root = Path(__file__).parents[1]
    html = (root / "docs/index.html").read_text(encoding="utf-8")
    assert html.count("data-stage=") == 5
    assert html.count("data-scenario=") == 5
    assert "payload_body: not retained" in html
    assert "WEBHOOK DELIVERY DEBUGGER" in html
    assert "Emmanuel Asika" in html
