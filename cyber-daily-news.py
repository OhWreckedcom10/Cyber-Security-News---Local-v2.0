#!/usr/bin/env python3
"""
Cyber Newsletter (LANDSCAPE PDF) — Magazine Template + Blue Spectrum Blocks (Sharp Rectangles)

This version includes:
- RSS aggregation from a curated list of security sources
- Scoring + de-duplication
- Image-stripping from summaries (skip embedded images in feed summaries)
- Landscape PDF newsletter with sharp rectangle cards + clickable links
- Optional WhatsApp sending via Twilio REST (NO twilio python SDK)
  - Text digest (optional)
  - PDF message (optional) using a PUBLIC HTTPS URL (e.g., GitHub RAW)

Important:
- WhatsApp PDF sending requires PUBLIC_BASE_URL to be set to a public HTTPS folder URL
  Example (GitHub RAW folder):
    PUBLIC_BASE_URL="https://raw.githubusercontent.com/OhWreckedcom10/Cyber-Security-News---Local-v2.0/main/reports"
    PUBLIC_PATH_PREFIX=""
"""

import os
import re
import io
import html
import math
import time
import calendar
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, List, Tuple

import feedparser
import pytz
import requests

from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.utils import simpleSplit


# ================= CONFIG ================= #

RSS_FEEDS: Dict[str, str] = {
    "The Hacker News": "https://thehackernews.com/feeds/posts/default",
    "Dark Reading": "https://www.darkreading.com/rss.xml",
    "SecurityWeek": "https://www.securityweek.com/feed/",
    "Krebs on Security": "https://krebsonsecurity.com/feed/",
    "CSO Online": "https://www.csoonline.com/feed/",
    "Schneier on Security": "https://www.schneier.com/feed/atom/",
    "Unsupervised Learning": "https://danielmiessler.com/feed/",
    "Tripwire": "https://www.tripwire.com/state-of-security/feed/",
    "Sophos News": "https://news.sophos.com/en-us/feed/",
    "WIRED Security": "https://www.wired.com/feed/category/security/latest/rss",
    "PCWorld Security": "https://www.pcworld.com/category/security/feed",
    "CNET Security": "https://www.cnet.com/rss/security/",
    "Cybersecurity Dive": "https://www.cybersecuritydive.com/feeds/news/",
    "The Last Watchdog": "https://thelastwatchdog.com/feed/",
    "SANS NewsBites": "https://www.sans.org/newsletters/newsbites/rss/",
}

KEYWORD_WEIGHTS: Dict[str, int] = {
    "zero-day": 40, "zero day": 35, "0day": 35,
    "ransomware": 35,
    "actively exploited": 45,
    "in the wild": 30,
    "data breach": 30,
    "breach": 20,
    "apt": 35,
    "critical": 20,
    "cve": 15,
    "remote code execution": 35,
    "rce": 25,
    "auth bypass": 25,
    "privilege escalation": 20,
    "malware": 20,
    "botnet": 20,
    "phishing": 10,
    "supply chain": 30,
}

SOURCE_WEIGHTS: Dict[str, int] = {
    "Krebs on Security": 25,
    "SANS NewsBites": 25,
    "Schneier on Security": 20,
    "The Hacker News": 20,
    "SecurityWeek": 20,
    "Sophos News": 18,
    "Unsupervised Learning": 18,
    "Dark Reading": 15,
    "Tripwire": 15,
    "Cybersecurity Dive": 14,
    "The Last Watchdog": 14,
    "CSO Online": 15,
    "WIRED Security": 12,
    "PCworld Security": 10,   # NOTE: kept as-is (typo in key doesn't break anything; only affects weighting)
    "CNET Security": 10,
}

TIMEZONE = pytz.UTC

TOP_N = int(os.getenv("TOP_N", "10"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "72"))
SUMMARY_MAX_CHARS = int(os.getenv("SUMMARY_MAX_CHARS", "240"))
MAX_KEYWORD_SCORE = int(os.getenv("MAX_KEYWORD_SCORE", "80"))
DUPLICATE_THRESHOLD = float(os.getenv("DUPLICATE_THRESHOLD", "0.93"))
SHOW_SIGNALS = os.getenv("SHOW_SIGNALS", "1").strip().lower() not in {"0", "false", "no"}
OUT_DIR = os.getenv("OUT_DIR", "out")

MAX_URL_LINES = int(os.getenv("MAX_URL_LINES", "2"))

# Optional send (NO twilio SDK)
SEND_WHATSAPP_TEXT = os.getenv("SEND_WHATSAPP_TEXT", "0").strip().lower() in {"1", "true", "yes"}
SEND_WHATSAPP_PDF = os.getenv("SEND_WHATSAPP_PDF", "0").strip().lower() in {"1", "true", "yes"}
WHATSAPP_MAX_LEN = int(os.getenv("WHATSAPP_MAX_LEN", "1500"))

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_WHATSAPP = os.getenv("FROM_WHATSAPP")
TO_WHATSAPP = os.getenv("TO_WHATSAPP")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")
PUBLIC_PATH_PREFIX = os.getenv("PUBLIC_PATH_PREFIX", OUT_DIR)

_WORD_BOUNDARY_TOKENS = {"apt", "cve", "rce"}


# ================= VISUAL THEME ================= #

BLUE_050 = colors.Color(0.94, 0.97, 1.00)
BLUE_075 = colors.Color(0.90, 0.95, 1.00)
BLUE_100 = colors.Color(0.85, 0.92, 1.00)
BLUE_BORDER = colors.Color(0.25, 0.50, 0.85)
BLUE_TEXT = colors.Color(0.10, 0.25, 0.45)

SIDEBAR_BG = colors.Color(0.14, 0.32, 0.55)
SIDEBAR_TEXT = colors.white
SIDEBAR_RULE = colors.Color(0.75, 0.85, 0.95)


# ================= UTIL ================= #

def now_utc() -> datetime:
    return datetime.now(TIMEZONE)


def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def safe_text(s: str) -> str:
    return html.unescape(s or "").strip()


def canonical_link(link: str) -> str:
    link = (link or "").strip()
    link = re.sub(r"#.*$", "", link)
    link = re.sub(r"[?&]utm_[^=&]+=[^&]+", "", link)
    link = re.sub(r"[?&]ref=[^&]+", "", link)
    link = re.sub(r"\?$", "", link)
    return link


def token_present(text: str, token: str) -> bool:
    t = token.lower().strip()
    if t in _WORD_BOUNDARY_TOKENS or len(t) <= 3:
        return re.search(rf"\b{re.escape(t)}\b", text) is not None
    return t in text


def fit_lines(text: str, font: str, size: float, max_width: float) -> List[str]:
    return simpleSplit(text or "", font, size, max_width)


def draw_rect(c: canvas.Canvas, x: float, y: float, w: float, h: float,
              fill_color, stroke_color, stroke_w: float = 0.8) -> None:
    c.setFillColor(fill_color)
    c.setStrokeColor(stroke_color)
    c.setLineWidth(stroke_w)
    c.rect(x, y, w, h, fill=1, stroke=1)
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)


def card_fill_for_score(score: float):
    return BLUE_075 if score >= 70 else BLUE_050


def risk_bar(score: float) -> str:
    level = int(round(max(0.0, min(100.0, score)) / 25.0))
    level = max(1, min(4, level))
    return "■" * level + "□" * (4 - level)


# ---------------- Summary cleaning: drop images ---------------- #

_IMG_TAG_RE = re.compile(r"(?is)<img\b[^>]*>")
_FIGURE_RE = re.compile(r"(?is)<figure\b[^>]*>.*?</figure>")
_PICTURE_RE = re.compile(r"(?is)<picture\b[^>]*>.*?</picture>")
_SVG_RE = re.compile(r"(?is)<svg\b[^>]*>.*?</svg>")
_IFRAME_RE = re.compile(r"(?is)<iframe\b[^>]*>.*?</iframe>")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_DATA_IMAGE_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")


def strip_images_from_html(raw: str) -> str:
    if not raw:
        return ""
    s = raw
    s = _FIGURE_RE.sub(" ", s)
    s = _PIICTURE_RE.sub(" ", s) if False else s  # kept harmless; do nothing
    s = _PICTURE_RE.sub(" ", s)
    s = _SVG_RE.sub(" ", s)
    s = _IFRAME_RE.sub(" ", s)
    s = _IMG_TAG_RE.sub(" ", s)
    s = _MD_IMAGE_RE.sub(" ", s)
    s = _DATA_IMAGE_RE.sub(" ", s)
    return s


def strip_html_to_text(raw: str) -> str:
    if not raw:
        return ""
    s = html.unescape(raw)
    s = strip_images_from_html(s)
    s = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<.*?>", " ", s)
    return normalize_space(s)


def shorten(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    cut = s[: max_chars + 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


# --- Smart URL wrapping ---
_URL_BREAK_CHARS = set("/?&=_-.#:")

def wrap_url_smart(c: canvas.Canvas, url: str, font: str, size: float, max_width: float) -> List[str]:
    url = (url or "").strip()
    if not url:
        return []
    c.setFont(font, size)

    lines: List[str] = []
    cur = ""
    last_break_pos = -1

    for ch in url:
        cand = cur + ch
        if ch in _URL_BREAK_CHARS:
            last_break_pos = len(cand)

        if c.stringWidth(cand, font, size) <= max_width:
            cur = cand
            continue

        if last_break_pos > 0:
            lines.append(cur[:last_break_pos].rstrip())
            cur = cur[last_break_pos:].lstrip() + ch if cur[last_break_pos:].lstrip() else ch
        else:
            if cur:
                lines.append(cur)
                cur = ch
            else:
                lines.append(ch)
                cur = ""

        last_break_pos = -1
        for i, cc in enumerate(cur, 1):
            if cc in _URL_BREAK_CHARS:
                last_break_pos = i

    if cur:
        lines.append(cur)
    return lines


def ellipsize_line_to_width(c: canvas.Canvas, text: str, font: str, size: float, max_width: float) -> str:
    text = (text or "")
    c.setFont(font, size)
    if c.stringWidth(text, font, size) <= max_width:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = text[:mid].rstrip() + ell
        if c.stringWidth(cand, font, size) <= max_width:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best or ell


# ================= SCORING ================= #

def recency_score(hours_old: float) -> float:
    midpoint = float(max(1, LOOKBACK_HOURS))
    spread = max(2.0, midpoint / 4.0)
    return 30.0 / (1.0 + math.exp((hours_old - midpoint) / spread))


def compute_score(article: Dict) -> float:
    text = (article["title"] + " " + article.get("summary", "")).lower()

    keyword_score = 0.0
    for keyword, weight in KEYWORD_WEIGHTS.items():
        if token_present(text, keyword):
            keyword_score += float(weight)

    score = min(keyword_score, float(MAX_KEYWORD_SCORE))
    score += float(SOURCE_WEIGHTS.get(article["source"], 10))

    hours_old = (now_utc() - article["published"]).total_seconds() / 3600.0
    score += max(0.0, recency_score(hours_old))

    return round(score, 1)


def scoring_signals(article: Dict) -> List[str]:
    signals: List[str] = []
    text = (article["title"] + " " + article.get("summary", "")).lower()

    hits: List[str] = []
    for keyword in KEYWORD_WEIGHTS:
        if token_present(text, keyword):
            hits.append("zero-day" if keyword == "zero day" else keyword)

    uniq: List[str] = []
    for h in hits:
        if h not in uniq:
            uniq.append(h)
    if uniq:
        signals.extend(uniq[:4])

    if SOURCE_WEIGHTS.get(article["source"], 10) >= 20:
        signals.append("trusted source")

    hours_old = (now_utc() - article["published"]).total_seconds() / 3600.0
    if hours_old <= 6:
        signals.append("breaking")
    elif hours_old <= 12:
        signals.append("recent")
    return signals


# ================= PARSING ================= #

def parse_entry_datetime(entry) -> Optional[datetime]:
    for attr in ("published", "updated"):
        ds = getattr(entry, attr, None)
        if ds:
            try:
                dt = parsedate_to_datetime(ds)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TIMEZONE)
                return dt.astimezone(TIMEZONE)
            except Exception:
                pass

    tm = None
    if getattr(entry, "published_parsed", None):
        tm = entry.published_parsed
    elif getattr(entry, "updated_parsed", None):
        tm = entry.updated_parsed
    if not tm:
        return None

    ts = calendar.timegm(tm)
    return datetime.fromtimestamp(ts, tz=TIMEZONE)


def extract_summary(entry) -> str:
    raw = ""

    if getattr(entry, "content", None):
        c0 = entry.content[0]
        if isinstance(c0, dict):
            raw = c0.get("value", "") or ""
        else:
            raw = getattr(c0, "value", "") or ""

    raw = raw or getattr(entry, "summary", "") or getattr(entry, "description", "") or ""

    text = strip_html_to_text(raw)
    return shorten(text, SUMMARY_MAX_CHARS)


def is_duplicate_title(title: str, seen_titles: List[str], threshold: float = DUPLICATE_THRESHOLD) -> bool:
    t = title.lower().strip()
    return any(SequenceMatcher(None, t, s.lower().strip()).ratio() > threshold for s in seen_titles)


def classify(item: Dict) -> str:
    text = (item.get("title", "") + " " + item.get("summary", "")).lower()
    if "zero-day" in text or "zero day" in text or "0day" in text or "actively exploited" in text:
        return "ZERO-DAYS"
    if "ransomware" in text:
        return "RANSOMWARE"
    if "breach" in text or "data breach" in text:
        return "BREACHES"
    if "phishing" in text:
        return "PHISHING"
    return "OTHER"


def collect_and_rank() -> List[Dict]:
    cutoff = now_utc() - timedelta(hours=LOOKBACK_HOURS)

    articles: List[Dict] = []
    seen_titles: List[str] = []
    seen_links: set[str] = set()

    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue

        for entry in getattr(feed, "entries", []):
            published = parse_entry_datetime(entry)
            if not published or published < cutoff:
                continue

            title = normalize_space(getattr(entry, "title", ""))
            link = canonical_link(getattr(entry, "link", ""))

            if not title:
                continue

            if link:
                if link in seen_links:
                    continue
                seen_links.add(link)

            if is_duplicate_title(title, seen_titles, DUPLICATE_THRESHOLD):
                continue
            seen_titles.append(title)

            article = {
                "title": safe_text(title),
                "summary": safe_text(extract_summary(entry)),
                "source": source,
                "published": published,
                "link": link,
            }
            article["score"] = compute_score(article)
            if SHOW_SIGNALS:
                article["signals"] = scoring_signals(article)
            articles.append(article)

    articles.sort(key=lambda x: x["score"], reverse=True)
    return articles[:TOP_N]


# ================= WHATSAPP TEXT HELPERS ================= #

def build_text_digest(news: List[Dict]) -> str:
    if not news:
        return f"Cybersecurity Briefing • Top {TOP_N} ({LOOKBACK_HOURS}h)\n\nNo qualifying items found."

    header = f"Cybersecurity Briefing • Top {min(TOP_N, len(news))} ({LOOKBACK_HOURS}h)\n\n"
    lines: List[str] = [header]

    for i, n in enumerate(news[:TOP_N], 1):
        hours_old = (now_utc() - n["published"]).total_seconds() / 3600.0
        bar = risk_bar(float(n.get("score", 0.0)))
        lines.append(f"{i}. {n.get('title','').strip()}")
        lines.append(f"{n.get('source','')} • {bar} {n.get('score','')} • {hours_old:.1f}h")
        summ = (n.get("summary") or "").strip()
        if summ:
            lines.append(summ)
        link = (n.get("link") or "").strip()
        if link:
            lines.append(link)
        lines.append("")

    return "\n".join(lines).strip()


def chunk_text(text: str, max_len: int = WHATSAPP_MAX_LEN) -> List[str]:
    text = (text or "").strip()
    if not text:
        return [""]

    if len(text) <= max_len:
        return [text]

    parts = text.split("\n\n")
    chunks: List[str] = []
    buf = ""

    for p in parts:
        p = p.strip()
        if not p:
            continue

        candidate = (buf + ("\n\n" if buf else "") + p).strip()
        if len(candidate) <= max_len:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
                buf = ""

            while len(p) > max_len:
                chunks.append(p[:max_len])
                p = p[max_len:]
            buf = p

    if buf:
        chunks.append(buf)

    return chunks


def prefix_parts(chunks: List[str]) -> List[str]:
    if len(chunks) <= 1:
        return chunks
    total = len(chunks)
    return [f"({i}/{total})\n{c}" for i, c in enumerate(chunks, 1)]


# ================= PDF ================= #

def build_pdf_bytes(news: List[Dict]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(LETTER))
    width, height = landscape(LETTER)

    margin = 0.55 * inch
    top = height - margin
    bottom = 0.65 * inch

    sidebar_w = 2.70 * inch
    gap = 0.30 * inch
    content_x = margin + sidebar_w + gap
    content_w = width - margin - content_x
    gutter = 0.25 * inch
    col_w = (content_w - gutter) / 2.0

    page_num = 1

    def draw_page_number(pn: int):
        c.setFont("Times-Roman", 9)
        c.setFillColor(colors.grey)
        c.drawRightString(width - margin, bottom - 0.18 * inch, f"{pn}")
        c.setFillColor(colors.black)

    def new_page():
        nonlocal page_num
        if page_num > 1:
            c.showPage()
        draw_page_number(page_num)
        page_num += 1

    def draw_sidebar(items: List[Dict]):
        x = margin
        y = top
        panel_h = top - bottom

        draw_rect(c, x, bottom, sidebar_w, panel_h, SIDEBAR_BG, SIDEBAR_BG, stroke_w=0.0)

        c.setFillColor(SIDEBAR_TEXT)
        c.setFont("Times-Bold", 18)
        c.drawString(x + 0.18 * inch, y - 0.45 * inch, "CYBER")
        c.drawString(x + 0.18 * inch, y - 0.78 * inch, "NEWSLETTER")

        c.setFont("Times-Roman", 9.5)
        dt = now_utc().strftime("%A, %b %d, %Y • %H:%M UTC")
        c.drawString(x + 0.18 * inch, y - 1.10 * inch, dt)

        c.setStrokeColor(SIDEBAR_RULE)
        c.setLineWidth(0.6)
        c.line(x + 0.18 * inch, y - 1.25 * inch, x + sidebar_w - 0.18 * inch, y - 1.25 * inch)

        pulse = {"ZERO-DAYS": 0, "RANSOMWARE": 0, "BREACHES": 0, "PHISHING": 0, "OTHER": 0}
        for it in items:
            pulse[classify(it)] += 1

        c.setFillColor(SIDEBAR_TEXT)
        c.setFont("Times-Bold", 10)
        c.drawString(x + 0.18 * inch, y - 1.52 * inch, "THREAT PULSE")

        c.setFont("Times-Roman", 9)
        yy = y - 1.72 * inch
        for k in ["ZERO-DAYS", "RANSOMWARE", "BREACHES", "PHISHING", "OTHER"]:
            c.drawString(x + 0.18 * inch, yy, f"{k.title():<12}  {pulse[k]}")
            yy -= 0.18 * inch

        c.setStrokeColor(SIDEBAR_RULE)
        c.setLineWidth(0.6)
        c.line(x + 0.18 * inch, yy - 0.08 * inch, x + sidebar_w - 0.18 * inch, yy - 0.08 * inch)

        yy -= 0.30 * inch
        c.setFillColor(SIDEBAR_TEXT)
        c.setFont("Times-Bold", 10)
        c.drawString(x + 0.18 * inch, yy, f"TOP {min(TOP_N, len(items))}")
        yy -= 0.22 * inch

        c.setFont("Times-Roman", 8.2)
        max_idx_w = sidebar_w - 0.36 * inch
        line_h = 0.16 * inch

        for i, it in enumerate(items[:min(TOP_N, len(items))], 1):
            t = shorten(it["title"], 150)
            lines = fit_lines(f"{i}. {t}", "Times-Roman", 8.2, max_idx_w)
            if len(lines) == 1 and c.stringWidth(lines[0], "Times-Roman", 8.2) > max_idx_w:
                lines = wrap_url_smart(c, f"{i}. {t}", "Times-Roman", 8.2, max_idx_w)
            lines = lines[:2]

            for line in lines:
                c.drawString(x + 0.18 * inch, yy, ellipsize_line_to_width(c, line, "Times-Roman", 8.2, max_idx_w))
                yy -= line_h
            yy -= 0.04 * inch
            if yy < bottom + 0.75 * inch:
                break

        c.setFont("Times-Roman", 8.2)
        c.setFillColor(SIDEBAR_TEXT)
        c.drawString(x + 0.18 * inch, bottom + 0.25 * inch, f"Lookback: {LOOKBACK_HOURS}h • Ranked by risk")
        c.setFillColor(colors.black)
        c.setStrokeColor(colors.black)

    def draw_section_block(sec: str, x: float, y_top: float, w: float) -> float:
        h = 0.22 * inch
        draw_rect(c, x, y_top - h, min(w, 2.4 * inch), h, BLUE_100, BLUE_BORDER, stroke_w=0.8)
        c.setFont("Times-Bold", 9)
        c.setFillColor(BLUE_TEXT)
        c.drawString(x + 8, y_top - h + 8, sec)
        c.setFillColor(colors.black)
        return y_top - (h + 0.16 * inch)

    def draw_story_card(x: float, y_top: float, w: float, item: Dict) -> float:
        inner_pad = 8
        max_w = w - 2 * inner_pad

        hl = fit_lines(item["title"], "Times-Bold", 11, max_w)
        headline_lines = min(2, len(hl))

        summ = safe_text(item.get("summary", "")).strip()
        slines = fit_lines(summ, "Times-Roman", 9.4, max_w) if summ else []
        summary_lines = min(3, len(slines))

        has_kicker = bool(SHOW_SIGNALS and item.get("signals"))
        url = (item.get("link") or "").strip()
        has_link = bool(url)

        link_lines: List[str] = []
        if has_link:
            link_lines = wrap_url_smart(c, url, "Times-Roman", 7.2, max_w)
            if len(link_lines) > MAX_URL_LINES:
                link_lines = link_lines[:MAX_URL_LINES]
                link_lines[-1] = ellipsize_line_to_width(c, link_lines[-1], "Times-Roman", 7.2, max_w)

        lh_head = 0.16 * inch
        lh_meta = 0.12 * inch
        lh_sum = 0.13 * inch
        lh_kick = 0.11 * inch
        lh_link = 0.11 * inch

        card_h = (
            12 / 72 * inch +
            headline_lines * lh_head +
            lh_meta +
            summary_lines * lh_sum +
            (lh_kick if has_kicker else 0) +
            (len(link_lines) * lh_link if has_link else 0) +
            12 / 72 * inch
        )

        fill = card_fill_for_score(item["score"])
        draw_rect(c, x, y_top - card_h, w, card_h, fill, BLUE_BORDER, stroke_w=0.9)

        tx = x + inner_pad
        ty = y_top - 12

        c.setFont("Times-Bold", 11)
        c.setFillColor(colors.black)
        for line in hl[:2]:
            c.drawString(tx, ty, line)
            ty -= lh_head

        hours_old = (now_utc() - item["published"]).total_seconds() / 3600.0
        bar = risk_bar(item["score"])
        meta = f"{item['source']} • {bar} {item['score']} • {hours_old:.1f}h"
        c.setFont("Times-Roman", 8.5)
        c.setFillColor(BLUE_TEXT)
        c.drawString(tx, ty, meta)
        c.setFillColor(colors.black)
        ty -= lh_meta

        if summ:
            c.setFont("Times-Roman", 9.4)
            for line in slines[:3]:
                c.drawString(tx, ty, line)
                ty -= lh_sum

        if has_kicker:
            sigs = item["signals"][:2]
            kicker = f"Why it matters: {', '.join(sigs)}."
            c.setFont("Times-Italic", 8.2)
            c.setFillColor(colors.grey)
            kline = fit_lines(kicker, "Times-Italic", 8.2, max_w)
            if kline:
                c.drawString(tx, ty, kline[0])
                ty -= lh_kick
            c.setFillColor(colors.black)

        if has_link and link_lines:
            c.setFont("Times-Roman", 7.2)
            c.setFillColor(colors.grey)
            for line in link_lines:
                c.drawString(tx, ty, line)
                tw = c.stringWidth(line, "Times-Roman", 7.2)
                c.linkURL(url, (tx, ty - 2, tx + tw, ty + 9), relative=0)
                ty -= lh_link
            c.setFillColor(colors.black)

        return y_top - card_h - 0.16 * inch

    new_page()
    if not news:
        draw_sidebar([])
        c.setFont("Times-Roman", 12)
        c.drawString(content_x, top - 0.6 * inch, "No qualifying items found.")
        c.showPage()
        c.save()
        return buf.getvalue()

    draw_sidebar(news)

    sections_order = ["ZERO-DAYS", "RANSOMWARE", "BREACHES", "PHISHING", "OTHER"]
    grouped: Dict[str, List[Dict]] = {k: [] for k in sections_order}
    for item in news:
        grouped[classify(item)].append(item)

    items: List[Tuple[str, Dict]] = []
    for sec in sections_order:
        for it in grouped[sec]:
            items.append((sec, it))

    col_x = [content_x, content_x + col_w + gutter]
    col_y = [top, top]
    current_col = 0

    def ensure_room(need: float):
        nonlocal current_col, col_y
        if col_y[current_col] - need >= bottom:
            return
        if current_col == 0 and col_y[1] - need >= bottom:
            current_col = 1
            return
        new_page()
        draw_sidebar(news)
        col_y[0] = top
        col_y[1] = top
        current_col = 0

    last_sec: Optional[str] = None

    for sec, item in items[:TOP_N]:
        if sec != last_sec:
            ensure_room(0.60 * inch)
            col_y[current_col] = draw_section_block(sec, col_x[current_col], col_y[current_col], col_w)
            last_sec = sec

        ensure_room(1.75 * inch)
        col_y[current_col] = draw_story_card(col_x[current_col], col_y[current_col], col_w, item)

        if col_y[0] < col_y[1] - 0.9 * inch:
            current_col = 1
        elif col_y[1] < col_y[0] - 0.9 * inch:
            current_col = 0

    c.showPage()
    c.save()
    return buf.getvalue()


def write_pdf_to_disk(pdf_bytes: bytes) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    fname = f"cyber_newsletter-{now_utc().strftime('%Y%m%d-%H%M')}.pdf"
    path = os.path.join(OUT_DIR, fname)
    with open(path, "wb") as f:
        f.write(pdf_bytes)
    return path


# ================= WHATSAPP SEND (optional) ================= #

def validate_twilio_config() -> None:
    missing = [k for k, v in {
        "TWILIO_ACCOUNT_SID": ACCOUNT_SID,
        "TWILIO_AUTH_TOKEN": AUTH_TOKEN,
        "FROM_WHATSAPP": FROM_WHATSAPP,
        "TO_WHATSAPP": TO_WHATSAPP,
    }.items() if not v]
    if missing:
        raise RuntimeError("Missing Twilio config: " + ", ".join(missing))
    if not str(FROM_WHATSAPP).startswith("whatsapp:"):
        raise RuntimeError("FROM_WHATSAPP must start with 'whatsapp:'.")
    if not str(TO_WHATSAPP).startswith("whatsapp:"):
        raise RuntimeError("TO_WHATSAPP must start with 'whatsapp:'.")


def twilio_send_message(body: str, media_url: Optional[str] = None) -> None:
    validate_twilio_config()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json"
    data = {"From": FROM_WHATSAPP, "To": TO_WHATSAPP, "Body": body}
    if media_url:
        if not media_url.startswith("https://"):
            raise ValueError("media_url must be a public HTTPS URL.")
        data["MediaUrl"] = media_url
    r = requests.post(url, data=data, auth=(ACCOUNT_SID, AUTH_TOKEN), timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Twilio API error {r.status_code}: {r.text}")


def pdf_public_url(filename: str) -> str:
    """
    Build a public URL for a PDF filename.
    If PUBLIC_BASE_URL already points at the reports folder, set PUBLIC_PATH_PREFIX="".
    """
    if not PUBLIC_BASE_URL:
        raise RuntimeError("PUBLIC_BASE_URL is not set (Twilio needs a public HTTPS URL).")
    filename = os.path.basename(filename)
    prefix = (PUBLIC_PATH_PREFIX or "").strip("/")
    if prefix:
        return f"{PUBLIC_BASE_URL.rstrip('/')}/{prefix}/{filename}"
    return f"{PUBLIC_BASE_URL.rstrip('/')}/{filename}"


# ================= MAIN ================= #

def main() -> None:
    news = collect_and_rank()
    print(f"Collected {len(news)} articles (TOP_N={TOP_N}, LOOKBACK_HOURS={LOOKBACK_HOURS})")

    pdf_bytes = build_pdf_bytes(news)
    pdf_path = write_pdf_to_disk(pdf_bytes)
    print(f"PDF generated: {pdf_path}")

    # Optional: send text digest
    if SEND_WHATSAPP_TEXT:
        digest = build_text_digest(news)
        for part in prefix_parts(chunk_text(digest, max_len=WHATSAPP_MAX_LEN)):
            twilio_send_message(part)
            time.sleep(1)
        print("WhatsApp text digest sent.")

    # Optional: send the PDF as WhatsApp media
    # NOTE: WhatsApp requires a PUBLIC HTTPS URL. Local file paths won't work.
    if SEND_WHATSAPP_PDF:
        # Usually you'll push/copy the PDF into your Git repo reports/ as "latest.pdf"
        # and set PUBLIC_BASE_URL to the GitHub RAW /reports folder URL.
        # So we send latest.pdf regardless of the local filename.
        public_pdf_url = pdf_public_url("latest.pdf")

        caption = f"Cybersecurity Briefing • Top {TOP_N} • {LOOKBACK_HOURS}h\n{public_pdf_url}"
        twilio_send_message(caption, media_url=public_pdf_url)
        print(f"WhatsApp PDF sent: {public_pdf_url}")

    if not SEND_WHATSAPP_TEXT and not SEND_WHATSAPP_PDF:
        print("Not sending via WhatsApp. Set SEND_WHATSAPP_TEXT=1 and/or SEND_WHATSAPP_PDF=1.")


if __name__ == "__main__":
    main()
