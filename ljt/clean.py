"""Tidies collected values for the results table and the Excel / CSV export. Never invents values: it only
removes noise (headings, markdown, stray symbols) and makes formats consistent."""
import re
from urllib.parse import unquote

WORKPLACES = ("Remote", "Hybrid", "On-site")
EMPLOYMENT = ("Full-time", "Part-time", "Contract", "Temporary", "Internship", "Volunteer", "Other")
_POSTED = re.compile(r"\b((?:re)?posted\s+)?(\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago)\b", re.I)


def title(t):
    """'| Java Full Stack Developer' -> 'Java Full Stack Developer'."""
    t = re.sub(r"\s+", " ", t or "").strip()
    return re.sub(r"^[\s|•·\-–—:,;]+", "", t).strip()


def description(d):
    """Drops LinkedIn's 'About the job' heading and markdown; one bullet style; at most one blank line."""
    if not d:
        return ""
    d = d.replace(" ", " ").replace("\r", "")
    d = re.sub(r"^\s*about the job\s*\n", "", d, flags=re.I)
    d = re.sub(r"\*\*(.+?)\*\*", r"\1", d)             # **bold** -> bold
    d = re.sub(r"__(.+?)__", r"\1", d)
    lines = []
    for line in d.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = re.sub(r"^(?:[*\-–▪◦●■►]|•)\s+", "• ", line)      # one bullet style
        lines.append(line)
    d = "\n".join(lines)
    d = re.sub(r"\n{3,}", "\n\n", d)
    return d.strip()


def size(s):
    """'501-1000' / '501-1,000' -> '501-1,000';  '10001+' -> '10,001+'."""
    s = (s or "").strip()
    m = re.fullmatch(r"([\d,]+)\s*-\s*([\d,]+)", s)
    if m:
        a, b = (int(x.replace(",", "")) for x in m.groups())
        return f"{a:,}-{b:,}"
    m = re.fullmatch(r"([\d,]+)\s*\+", s)
    return f"{int(m.group(1).replace(',', '')):,}+" if m else s


def location(loc):
    """'India (Remote)' -> ('India', 'Remote'). The workplace in brackets is moved to its own column."""
    loc = re.sub(r"\s+", " ", loc or "").strip()
    m = re.search(r"\s*\((remote|hybrid|on-site)\)\s*$", loc, re.I)
    if not m:
        return loc, ""
    wp = next(w for w in WORKPLACES if w.lower() == m.group(1).lower())
    return loc[:m.start()].strip(" ,"), wp


def workplace(loc_workplace, tags):
    if loc_workplace:
        return loc_workplace
    return next((w for w in WORKPLACES if w in (tags or [])), "")


def employment(tags):
    return ", ".join(t for t in EMPLOYMENT if t in (tags or []))


def posted(text):
    """'Posted 5 days ago' / 'Reposted 2 weeks ago' / '5 days ago' -> '5 days ago' (or 'Reposted 2 weeks ago')."""
    m = _POSTED.search(text or "")
    if not m:
        return ""
    return ("Reposted " if (m.group(1) or "").lower().startswith("re") else "") + m.group(2)


def contacts(links):
    """Decodes profile links so names are readable ('ve%C4%8De%C5%99a' -> 'večeřa'); one per line."""
    out = []
    for u in (links or "").split(";"):
        u = u.strip()
        if u and unquote(u) not in out:
            out.append(unquote(u))
    return "\n".join(out)
