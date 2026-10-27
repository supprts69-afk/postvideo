"""Text helpers: hashtags, title/body split, slugs, links. No third-party imports."""
import re
import secrets
import unicodedata

# \u0980-\u09FF = Bengali block (matras/vowel signs \w te dhore na, tai explicit)
_W = r"\w\u0980-\u09FF"
HASHTAG_RE = re.compile(rf"(?<![{_W}])#([{_W}]{{2,50}})")
URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.I)

MAX_TITLE = 100
MAX_TAGS = 10


def hashtags(text: str) -> list[str]:
    """Unique, lowercase hashtags (without '#'), original order."""
    seen, out = set(), []
    for m in HASHTAG_RE.finditer(text or ""):
        t = m.group(1).lower()
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:MAX_TAGS]


def merge_tags(*lists: list[str]) -> list[str]:
    seen, out = set(), []
    for lst in lists:
        for t in lst or []:
            t = str(t).strip().lstrip("#").lower()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out[:MAX_TAGS]


def strip_hashtags(text: str) -> str:
    """Remove #tags, tidy spaces, keep line breaks."""
    text = HASHTAG_RE.sub("", text or "")
    lines = [re.sub(r"[ \t]{2,}", " ", ln).strip() for ln in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _cut(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0] or s[:n]
    return cut.rstrip(" ,.;:-") + "…"


def split_title_body(text: str) -> tuple[str | None, str | None]:
    """First line = title. Rest = body. Long first line -> cut title, body keeps full text."""
    text = (text or "").strip()
    if not text:
        return None, None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first = lines[0]
    if len(first) > MAX_TITLE:
        return _cut(first, MAX_TITLE), text
    rest = "\n".join(lines[1:]).strip()
    return first, (rest or None)


def extract_urls(text: str) -> list[str]:
    out, seen = [], set()
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,;:!?")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def append_urls(body: str | None, urls: list[str]) -> str | None:
    """Add links (e.g. hidden behind formatted words) that are missing from body."""
    missing = [u for u in urls if u not in (body or "")]
    if not missing:
        return body
    return ((body + "\n\n") if body else "") + "\n".join(missing)


def _ascii_slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def make_slug(title: str, fallback: str = "video") -> str:
    """ascii-title + 6 hex (same shape as existing slugs)."""
    base = _ascii_slug(title)[:60].strip("-") or fallback
    return f"{base}-{secrets.token_hex(3)}"


def tag_slug(name: str) -> str:
    return re.sub(rf"[^{_W}]+", "-", (name or "").lower()).strip("-")[:40]
