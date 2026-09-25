"""Restore public ODOT SCD references (PDFs remain outside version control).

Run from any directory: python scripts/sync_odot_scds.py [--refresh]
Existing PDFs are retained unless --refresh is explicitly supplied.
The generated manifest records source URLs and content hashes, not a claim
that older local copies match the currently published revision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import urlopen


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(v for k, v in attrs if k == "href" and v)


def fetch(url: str, timeout: float) -> bytes:
    # Scraped hrefs feed this; urllib would also honour file:// and others.
    parts = urlparse(url)
    if parts.scheme != "https" or parts.hostname != "www.dot.state.oh.us":
        raise ValueError(f"Refusing non-ODOT URL: {url}")
    with urlopen(url, timeout=timeout) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return response.read()


def sync(root: Path, *, refresh: bool = False) -> list[dict]:
    records = []
    for family in ("structural", "roadway", "hydraulic"):
        index = f"https://www.dot.state.oh.us/SCDs/Pages/{family}.aspx"
        parser = Links()
        parser.feed(fetch(index, 60).decode("utf-8", errors="replace"))
        for url in sorted({urljoin(index, h) for h in parser.hrefs}):
            name = unquote(Path(urlparse(url).path).name)
            # Individual drawings only; exclude complete sets and revision packets.
            if not re.fullmatch(r"[A-Z]+[A-Z0-9]*-[0-9][A-Za-z0-9_.-]*\.pdf", name):
                continue
            directory = root if family == "structural" else root / family
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / name
            downloaded = refresh or not path.exists()
            if downloaded:
                data = fetch(url, 90)
                if not data.startswith(b"%PDF-"):
                    raise ValueError(f"Not a PDF: {url}")
                temporary = path.with_suffix(".pdf.part")
                temporary.write_bytes(data)
                temporary.replace(path)
            data = path.read_bytes()
            if not data.startswith(b"%PDF-"):
                raise ValueError(f"Invalid local PDF: {path}")
            records.append(dict(path=path.relative_to(root).as_posix(),
                                url=url, sha256=hashlib.sha256(data).hexdigest(),
                                bytes=len(data), fetched_this_run=downloaded))
            print(f"{'Fetched' if downloaded else 'Kept'} {path.name}", flush=True)
    # GR-3.4 is a plan insert, not linked by the SCD indexes. BDM 309.4.3.5
    # specifies this Type 4 transition for the DBR-3 retrofit railing.
    path = root / "plan_inserts" / "GR-3.4.pdf"
    url = "https://www.dot.state.oh.us/PIS/Roadway/GR-3.4%20-%20Bridge%20Terminal%20Assembly,%20Type%204.pdf"
    downloaded = refresh or not path.exists()
    if downloaded:
        data = fetch(url, 90)
        if not data.startswith(b"%PDF-"):
            raise ValueError(f"Not a PDF: {url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".pdf.part")
        temporary.write_bytes(data)
        temporary.replace(path)
    data = path.read_bytes()
    records.append(dict(path=path.relative_to(root).as_posix(), url=url,
                        sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                        fetched_this_run=downloaded))
    (root / "manifest.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1] / "res" / "odot_scds")
    args = parser.parse_args()
    print(f"Indexed {len(sync(args.root, refresh=args.refresh))} drawings")
