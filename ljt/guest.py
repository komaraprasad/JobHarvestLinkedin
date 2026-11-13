"""Fast mode: parses LinkedIn's lightweight public job pages, fetched by the extension in the person's own browser.

  search   /jobs-guest/jobs/api/seeMoreJobPostings/search?<classic filters>&start=N   -> up to 10 job cards
  job      /jobs-guest/jobs/api/jobPosting/<id>                                     -> title, company, description, criteria
  company  /company/<slug>  (fetched without cookies)                               -> Industry, Company size

Each is ~1 s and needs no page rendering, so jobs are read in parallel. Verified against real responses saved on
2026-11-13 (tests/fixtures/guest_*.html). Nothing is guessed: a value missing from the page stays blank.
"""
import html as _html
import re
from html.parser import HTMLParser
from urllib.parse import urlencode

GUEST_SEARCH = "/jobs-guest/jobs/api/seeMoreJobPostings/search"
GUEST_JOB = "/jobs-guest/jobs/api/jobPosting/"
PER_REQUEST = 10                     # cards per guest search request


def _text(fragment):
    """HTML fragment -> readable text (line breaks for <br>, <p>, <li>)."""
    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.out = []

        def handle_starttag(self, tag, attrs):
            if tag in ("br", "p", "li", "div", "ul", "ol", "h1", "h2", "h3"):
                self.out.append("\n")
            if tag == "li":
                self.out.append("• ")

        def handle_endtag(self, tag):
            if tag in ("p", "li", "ul", "ol", "div"):
                self.out.append("\n")

        def handle_data(self, data):
            self.out.append(data)
    p = P()
    p.feed(fragment or "")
    t = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _one(pattern, s, flags=re.S):
    m = re.search(pattern, s or "", flags)
    return _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""


def search_url(base, query, start):
    """Guest search address for LinkedIn's classic filter parameters (see search._base_query)."""
    q = {k: v for k, v in query.items() if v not in ("", None) and k not in ("start", "currentJobId")}
    if start:
        q["start"] = start
    return f"{base}{GUEST_SEARCH}?" + urlencode(q)


def parse_search(page):
    """Job cards from one guest search response: [{id, title, company, location, listed}] in page order."""
    cards, seen = [], set()
    for blk in re.split(r"<li\b[^>]*>", page or "")[1:]:
        jid = _one(r"urn:li:jobPosting:(\d+)", blk)
        if not jid or jid in seen:
            continue
        seen.add(jid)
        cards.append({
            "id": jid,
            "title": _one(r'base-search-card__title[^>]*>(.*?)<', blk),
            "company": _one(r'base-search-card__subtitle[^>]*>.*?>(.*?)<', blk),
            "location": _one(r'job-search-card__location[^>]*>(.*?)<', blk),
            "listed": _one(r'<time[^>]*datetime="([^"]+)"', blk),
        })
    return cards


def _profile(url):
    """'https://in.linkedin.com/in/nitin-patil-ust?trk=x' -> 'https://www.linkedin.com/in/nitin-patil-ust/'."""
    m = re.search(r"linkedin\.com/in/([A-Za-z0-9_%\-]+)", url or "")
    return f"https://www.linkedin.com/in/{m.group(1)}/" if m else ""


def contacts(page):
    """Hiring contacts shown on the public job page: the job poster ('Direct message the job poster from …') and
    profile links written in the description. Same sources as the signed-in reader; nothing is guessed."""
    out = []
    m = re.search(r'<div class="message-the-recruiter">(.*?)</section>', page or "", re.S)
    if m:
        for href in re.findall(r'<a class="base-card__full-link[^"]*"[^>]*href="([^"]+)"', m.group(1)):
            p = _profile(href)
            if p and p not in out:
                out.append(p)
    d = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', page or "", re.S)
    for href in re.findall(r'href="([^"]*linkedin\.com/in/[^"]+)"', d.group(1) if d else ""):
        p = _profile(_html.unescape(href))
        if p and p not in out:
            out.append(p)
    return out


def parse_job(page):
    """One job from its guest page, in the same shape the extension's page reader sends (see ExtStore.add_card)."""
    criteria = {_html.unescape(k.strip()): _html.unescape(re.sub(r"\s+", " ", v)).strip()
                for k, v in re.findall(r'description__job-criteria-subheader">\s*(.*?)\s*</h3>\s*<span[^>]*>(.*?)</span>',
                                       page or "", re.S)}
    m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', page or "", re.S)
    description = _text(m.group(1)) if m else ""
    company_url = _one(r'topcard__org-name-link[^>]*href="([^"?]+)', page)
    tags = [criteria["Employment type"]] if criteria.get("Employment type") else []
    people = contacts(page)
    notes = ["read from LinkedIn's public job page (workplace is not shown there"
             + ("" if people else "; this job shows no job poster") + ")"]
    title = _one(r'topcard__title[^>]*>(.*?)<', page)
    if not title:
        notes.append("job title not found")
    if not description:
        notes.append("description not found")
    return {
        "job_title": title,
        "company_name": _one(r'topcard__org-name-link[^>]*>(.*?)<', page),
        "company_url": company_url,
        "location": _one(r'topcard__flavor topcard__flavor--bullet[^>]*>(.*?)<', page),
        "job_description": description,
        "pane_tags": tags,
        "posted": _one(r'posted-time-ago__text[^>]*>(.*?)<', page),
        "seniority": criteria.get("Seniority level", ""),
        "job_industry": criteria.get("Industries", ""),
        "contact_profile_links": "; ".join(people),
        "data_notes": "; ".join(notes),
        "source": "guest",
    }


def parse_company(page):
    """Industry and Company size from a public company page (the 'About us' list)."""
    def dd(test_id):
        return _one(rf'data-test-id="about-us__{test_id}".*?<dd[^>]*>(.*?)</dd>', page)
    industry, size = dd("industry"), dd("size")
    size = re.sub(r"\s*employees\s*$", "", size, flags=re.I)
    return {"industry": industry, "size": size,
            "status": "ok" if (industry or size) else "not found",
            "note": "" if (industry or size) else "public company page shows no Industry / Company size"}
