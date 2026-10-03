"""Polite HTTP fetching: robots.txt checks, rate limiting, retries."""
import gzip
import re
import time
import urllib.robotparser

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0 Safari/537.36")


class Fetcher:
    def __init__(self, delay=1.0, log=print):
        self.delay = delay
        self.log = log
        self._last = 0.0
        self._robots = {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})

    def allowed(self, url):
        host = re.match(r"https?://[^/]+", url).group(0)
        if host not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                text = self.session.get(host + "/robots.txt", timeout=20).text
                parser.parse(text.splitlines())
            except requests.RequestException:
                parser.parse([])
            self._robots[host] = parser
        return self._robots[host].can_fetch(UA, url)

    def _wait(self):
        remaining = self._last + self.delay - time.time()
        if remaining > 0:
            time.sleep(remaining)
        self._last = time.time()

    def get(self, url, tries=3):
        """Return the page text, or None if disallowed/failed."""
        if not self.allowed(url):
            self.log(f"robots.txt disallows {url}")
            return None
        for attempt in range(tries):
            self._wait()
            try:
                resp = self.session.get(url, timeout=40)
            except requests.RequestException as exc:
                self.log(f"{url}: {exc}")
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 200:
                if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                    resp.encoding = "utf-8"  # servers omit the charset; requests would guess Latin-1
                if url.endswith(".gz"):
                    try:
                        return gzip.decompress(resp.content).decode("utf-8", "ignore")
                    except OSError:
                        pass
                return resp.text
            if resp.status_code in (403, 429, 503):
                self.log(f"{url}: HTTP {resp.status_code}, backing off")
                time.sleep(10 * (attempt + 1))
                continue
            self.log(f"{url}: HTTP {resp.status_code}")
            return None
        return None
