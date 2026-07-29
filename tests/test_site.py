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
    assert {"top", "stream", "trace", "architecture", "quickstart"} <= parser.ids
    assert "site.css" in parser.links
    assert (root / "docs/site.css").stat().st_size > 10_000
    assert "assets/webhook-observatory.webp" in (
        root / "docs/index.html"
    ).read_text(encoding="utf-8")
    assert (root / "docs/assets/webhook-observatory.webp").stat().st_size > 40_000
    assert (root / "docs/assets/packet-field.webp").stat().st_size > 40_000
    assert (root / "docs/assets/delivery-evidence.webp").stat().st_size > 40_000


def test_pages_site_explains_the_real_workflow_and_example():
    root = Path(__file__).parents[1]
    html = (root / "docs/index.html").read_text(encoding="utf-8")
    assert "not retained" in html
    assert "Duplicate fulfilment after provider timeout" in html
    assert "Webhook Delivery Debugger" in html
    assert "Emmanuel Asika" in html


def test_pages_site_has_webhook_specific_states_and_formatted_code():
    root = Path(__file__).parents[1]
    html = (root / "docs/index.html").read_text(encoding="utf-8")
    css = (root / "docs/site.css").read_text(encoding="utf-8")
    for state in ("Processed", "Safe retry", "Rejected", "ID collision"):
        assert state in html
    assert 'class="prompt"' in html
    assert 'class="success"' in html
    assert 'class="warning"' in html
    assert 'aria-label="Webhook receiver decision pipeline"' in html
    assert "overflow:auto" in css
    for color in ("--green:", "--amber:", "--red:", "--blue:"):
        assert color in css


def test_pages_site_has_interactive_investigation_and_social_metadata():
    root = Path(__file__).parents[1]
    html = (root / "docs/index.html").read_text(encoding="utf-8")
    assert 'property="og:image"' in html
    assert 'name="twitter:card"' in html
    assert 'data-filter="duplicate"' in html
    assert 'data-detail="collision"' in html
    assert 'data-stage="conclude"' in html
    assert 'data-copy' in html
    assert "navigator.clipboard.writeText" in html
