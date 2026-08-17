"""Client for the TS RERA public search at rerait.telangana.gov.in.

The search endpoint is gated by a server-side image captcha. This client
handles everything except reading that captcha: the solve is supplied by a
caller-provided callback, which is expected to put a human in the loop.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

BASE = "https://rerait.telangana.gov.in"
SEARCH = f"{BASE}/SearchList/Search"
CAPTCHA = f"{BASE}/SearchList/SearchCaptcha"
GET_DISTRICT = f"{BASE}/SearchList/GetDistrict"
GET_TALUKA = f"{BASE}/SearchList/GetTaluka"
GET_VILLAGE = f"{BASE}/SearchList/GetVillage"

CERT_BUNDLE = Path(__file__).parent / "certs" / "bundle.pem"

# The server presents only its leaf cert and omits the emSign intermediate,
# so the stock certifi bundle cannot build a chain. bundle.pem is certifi plus
# that intermediate -- verification stays on.
TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')

# The page reports captcha trouble through sweetalert with several wordings:
#   "Captcha is not valid." -- wrong answer against an active captcha
#   "Please Enter Captcha."  -- no live captcha in session / blank submission
#   "Invalid Captcha."       -- seen on some paths
# Any of these means the solve did not take; treat them all as a rejection.
CAPTCHA_ERRORS = (
    "captcha is not valid",
    "please enter captcha",
    "invalid captcha",
)


class CaptchaRejected(Exception):
    """The server rejected the supplied captcha text."""


class TokenExpired(Exception):
    """The per-row detail token is no longer valid (server returns Unauthorized).

    Detail tokens are time-limited, so they must be fetched within a short
    window of being harvested -- enrich inline, not in a later pass.
    """


@dataclass
class Options:
    """One row of the search form."""

    type: str = "Promoter"  # or "Agent"
    district: str | int | None = None
    taluka: str | int | None = None
    village: str | int | None = None
    project: str = ""
    promoter: str = ""
    agent_name: str = ""
    certi_no: str = ""
    ptype: str | int | None = None
    plot_bearing: str = ""
    completion_from: str = ""
    completion_to: str = ""


@dataclass
class Client:
    delay: float = 1.5
    timeout: int = 60
    session: requests.Session = field(default_factory=requests.Session)
    _last: float = 0.0

    def __post_init__(self) -> None:
        self.session.verify = str(CERT_BUNDLE)
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    # -- reference data (open endpoints, no captcha) ----------------------

    def districts(self) -> list[dict]:
        """Districts come pre-rendered in the form, not from an endpoint."""
        self._throttle()
        html = self.session.get(SEARCH, timeout=self.timeout).text
        soup = BeautifulSoup(html, "html.parser")
        sel = soup.find("select", id="District")
        return [
            {"id": int(o["value"]), "name": o.get_text(strip=True)}
            for o in sel.find_all("option")
            if o.get("value")
        ]

    def _lookup(self, url: str, payload: dict) -> list[dict]:
        self._throttle()
        r = self.session.post(
            url,
            json=payload,
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def talukas(self, district_id: int) -> list[dict]:
        return self._lookup(GET_TALUKA, {"DisID": int(district_id)})

    def villages(self, taluka_id: int) -> list[dict]:
        return self._lookup(GET_VILLAGE, {"TalukaID": int(taluka_id)})

    # -- captcha-gated search --------------------------------------------

    def _token(self) -> str:
        self._throttle()
        html = self.session.get(SEARCH, timeout=self.timeout).text
        m = TOKEN_RE.search(html)
        if not m:
            raise RuntimeError("anti-forgery token not found on search page")
        return m.group(1)

    def detail(self, token: str) -> str:
        """Fetch a project's full PrintPreview detail page. No captcha.

        Tokens are scraped already URL-encoded; unquote once so requests'
        own encoding does not double-escape the %2b/%2f/%3d in the blob.
        """
        self._throttle()
        r = self.session.get(
            f"{BASE}/PrintPreview/PrintPreview",
            params={"q": unquote(token)},
            timeout=self.timeout,
        )
        r.raise_for_status()
        # Expired/invalid tokens 302 to /Error/UnauthorizedPage, which renders a
        # tiny "Unauthorized Access." page.
        if "unauthorized access" in r.text.lower() or "/Error/Unauthorized" in r.url:
            raise TokenExpired(token[:24] + "...")
        return r.text

    def captcha_image(self, dest: Path) -> Path:
        """Download the current captcha for this session into `dest`."""
        self._throttle()
        r = self.session.get(
            CAPTCHA, params={"_": int(time.time() * 1000)}, timeout=self.timeout
        )
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return dest

    def _opts_fields(self, opts: Options) -> dict:
        return {
            "Type": opts.type,
            "Project": opts.project,
            "Promoter": opts.promoter,
            "AgentName": opts.agent_name,
            "CertiNo": opts.certi_no,
            "District": "" if opts.district is None else str(opts.district),
            "Taluka": "" if opts.taluka is None else str(opts.taluka),
            "Village": "" if opts.village is None else str(opts.village),
            "PType": "" if opts.ptype is None else str(opts.ptype),
            "PlotBearing": opts.plot_bearing,
            "CompletionDate_From": opts.completion_from,
            "CompletionDate_To": opts.completion_to,
        }

    def _post(self, form: dict, captcha_text: str) -> str:
        self._throttle()
        r = self.session.post(
            SEARCH, data=form, headers={"Referer": SEARCH}, timeout=self.timeout
        )
        r.raise_for_status()
        low = r.text.lower()
        for err in CAPTCHA_ERRORS:
            if err in low:
                raise CaptchaRejected(f"{err!r} (sent {captcha_text!r})")
        return r.text

    def search(
        self,
        opts: Options,
        captcha_text: str,
        token: str | None = None,
        page: int = 1,
    ) -> str:
        """Run a fresh search (page 1). Returns raw results HTML.

        Raises CaptchaRejected if the server did not accept `captcha_text`.
        """
        form = {
            "__RequestVerificationToken": token or self._token(),
            **self._opts_fields(opts),
            "pageTraverse": str(page),
            "Captcha": captcha_text,
            "Command": "Search",
        }
        return self._post(form, captcha_text)

    def paginate(
        self,
        opts: Options,
        state: dict,
        captcha_text: str = "",
        command: str = "Next",
    ) -> str:
        """Move within an existing result set using the server pager.

        `state` carries the fields the pager echoes back -- token, TotalRecords,
        TotalPages, CurrentPage. `captcha_text` may be empty: if the server
        still holds this session's captcha it is ignored, and only if it demands
        a fresh one does this raise CaptchaRejected.
        """
        form = {
            "__RequestVerificationToken": state["token"],
            **self._opts_fields(opts),
            "pageTraverse": str(state.get("CurrentPage", 1)),
            "CurrentPage": str(state.get("CurrentPage", 1)),
            "TotalRecords": str(state.get("TotalRecords", "")),
            "TotalPages": str(state.get("TotalPages", "")),
            "Captcha": captcha_text,
            "Command": command,
        }
        return self._post(form, captcha_text)


def parse_results(html: str) -> tuple[list[str], list[dict]]:
    """Pull the result grid out of a search response.

    Returns (columns, rows). An empty result set yields ([], []) -- note the
    page ships a hidden "No Records Found" block even before any search, so
    presence of that text proves nothing; only the grid does.
    """
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.find(id="gridview") or soup.find(id="DivBind") or soup
    table = grid.find("table")
    if table is None:
        return [], []

    cols: list[str] = [th.get_text(" ", strip=True) for th in table.find_all("th")]
    rows: list[dict] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        vals = [td.get_text(" ", strip=True) for td in cells]
        # Keep any document/certificate links hanging off the row.
        links = [a.get("href") or a.get("onclick", "") for a in tr.find_all("a")]
        row = dict(zip(cols, vals)) if cols else {f"col{i}": v for i, v in enumerate(vals)}
        if len(vals) > len(cols) and cols:
            row["_extra"] = vals[len(cols) :]
        row["_links"] = [x for x in links if x]
        rows.append(row)
    return cols, rows


DETAIL_RE = re.compile(r"/PrintPreview/PrintPreview\?q=([^\"'&\s]+)")


def parse_state(html: str) -> dict:
    """Page-state the pager needs to keep going."""
    soup = BeautifulSoup(html, "html.parser")

    def val(el_id: str, default: str = "") -> str:
        el = soup.find(id=el_id)
        return el.get("value", default) if el else default

    tok = soup.find("input", attrs={"name": "__RequestVerificationToken"})
    return {
        "token": tok["value"] if tok else "",
        "TotalRecords": int(val("TotalRecords", "0") or 0),
        "TotalPages": int(val("TotalPages", "0") or 0),
        "CurrentPage": int(val("CurrentPage", "0") or 0),
    }


def row_tokens(html: str) -> list[str]:
    """The encrypted per-row PrintPreview tokens, in page order."""
    seen: dict[str, None] = {}
    for m in DETAIL_RE.finditer(html):
        seen.setdefault(m.group(1), None)
    return list(seen)


def parse_pages(html: str) -> list[int]:
    """Page numbers offered by the pager (elements carrying data-pg)."""
    soup = BeautifulSoup(html, "html.parser")
    out: set[int] = set()
    for el in soup.select("[data-pg]"):
        raw = (el.get("data-pg") or "").strip()
        if raw.isdigit():
            out.add(int(raw))
    return sorted(out)


def _open_in_viewer(path: Path) -> bool:
    """Best-effort: pop the image open so a terminal user can read it.

    Tries the VS Code CLI (Codespaces/remote), then xdg-open/open. Returns True
    if something was launched.
    """
    import shutil
    import subprocess

    for cmd in ("code", "code-insiders", "xdg-open", "open"):
        exe = shutil.which(cmd)
        if not exe:
            continue
        try:
            # `code -r` reuses the current window; openers just take the path.
            args = [exe, "-r", str(path)] if "code" in cmd else [exe, str(path)]
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False


def prompt_captcha(client: Client, workdir: Path) -> str:
    """Human-in-the-loop solve: save the image, open it, ask the operator."""
    path = client.captcha_image(workdir / "captcha.png").resolve()
    opened = _open_in_viewer(path)
    print(f"\n  captcha image: {path}")
    if opened:
        print("  (opened in your editor -- it refreshes each attempt; look at the newest)")
    else:
        print("  open that file to read it (in VS Code: click it in the Explorer).")
    print("  type the characters you see (case matters).")
    return input("  captcha> ").strip()


CaptchaSolver = Callable[[Client, Path], str]
