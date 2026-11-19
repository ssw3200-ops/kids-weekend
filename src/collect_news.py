"""기사 기반 지역 행사 수집 (키 없는 무료 뉴스 RSS)

공공 API에 안 올라오는 시·군·구, 읍·면 단위 축제·행사는 대부분
"지자체 보도자료 → 통신사 기사"로 알려집니다. 그 기사를 모아
행사명·날짜·시간·장소를 뽑아냅니다.

- 검색: 빙 뉴스 RSS(요약문·원문 링크 포함) + 구글 뉴스 RSS(제목만)
- 원문 기사 페이지에서 요약(og:description)과 본문 앞부분만 읽어 사실 정보만 추출
- 기사 본문·사진은 저장하지 않음 (행사명·날짜·장소 + 기사 링크만)
- 처리한 기사는 docs/cache/news_cache.json 에 결과만 캐시
"""
from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests

from common import KST, Event

CACHE = Path(__file__).resolve().parent.parent / "docs" / "cache" / "news_cache.json"
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}

# 지역 검색어: 시·도 + 사람들이 기사에서 쓰는 이름
REGION_QUERY = {
    "서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천", "광주": "광주광역시",
    "대전": "대전", "울산": "울산", "세종": "세종시", "경기": "경기", "강원": "강원",
    "충북": "충북", "충남": "충남", "전북": "전북", "전남": "전남", "경북": "경북",
    "경남": "경남", "제주": "제주",
}
KEYWORDS = ["축제 개최", "어린이 행사", "가족 축제", "체험 행사"]

KID_WORDS = ["어린이", "아이", "아동", "유아", "가족", "키즈", "체험", "놀이", "동화", "인형극", "산타",
             "크리스마스", "축제", "페스티벌", "한마당", "공연", "마켓", "장터", "빛"]
BAD_WORDS = ["채용", "취업", "일자리", "세미나", "포럼", "학술", "선거", "주류", "와인", "맥주",
             "부동산", "분양", "주식", "사망", "사고", "화재", "폭행", "구속", "기소", "재판", "의회",
             "예산", "조례", "취소", "연기", "결과", "성료", "마무리", "폐막", "막 내려", "다녀간", "찾았다"]
EVENT_WORDS = ("축제", "행사", "페스티벌", "한마당", "잔치", "마켓", "장터", "체험", "공연", "축전",
               "박람회", "놀이터", "캠프", "음악회", "콘서트", "전시", "대회")

DEBUG: dict = {}


# ── RSS ───────────────────────────────────────────────────────
def _get(url: str, timeout: int = 15) -> requests.Response | None:
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.ok:
            return r
    except Exception:  # noqa: BLE001
        pass
    return None


def _rss_items(xml_bytes: bytes) -> list[dict]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        src = ""
        for ch in it:
            if ch.tag.endswith("Source") or ch.tag == "source":
                src = (ch.text or "").strip()
        out.append({"title": (it.findtext("title") or "").strip(),
                    "link": (it.findtext("link") or "").strip(),
                    "desc": re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or "")).strip(),
                    "pub": (it.findtext("pubDate") or "").strip(), "source": src})
    return out


def bing(query: str) -> list[dict]:
    r = _get(f"https://www.bing.com/news/search?q={quote(query)}&format=rss&mkt=ko-KR&setlang=ko")
    items = _rss_items(r.content) if r else []
    for it in items:  # apiclick 링크에서 원문 주소 꺼내기
        qs = parse_qs(urlparse(it["link"]).query)
        if "url" in qs:
            it["link"] = qs["url"][0]
        if " - " in it["title"] and not it["source"]:
            t, s = it["title"].rsplit(" - ", 1)
            it["title"], it["source"] = t.strip(), s.strip()
        if not it["source"]:
            it["source"] = urlparse(it["link"]).netloc.replace("www.", "")
    return items


def google(query: str) -> list[dict]:
    r = _get(f"https://news.google.com/rss/search?q={quote(query + ' when:14d')}&hl=ko&gl=KR&ceid=KR:ko")
    items = _rss_items(r.content) if r else []
    for it in items:  # 구글 제목은 "제목 - 언론사"
        if " - " in it["title"]:
            t, s = it["title"].rsplit(" - ", 1)
            it["title"], it["source"] = t.strip(), it["source"] or s.strip()
    return items


# ── 기사 본문 ──────────────────────────────────────────────────
def article_text(url: str) -> str:
    """og:description + 본문 앞부분(문단 텍스트)만. 저장하지 않고 추출에만 사용"""
    if "news.google.com" in url:
        return ""
    r = _get(url, timeout=12)
    if not r:
        return ""
    r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
    h = r.text
    meta = " ".join(html.unescape(m) for m in re.findall(
        r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']+)', h)[:2])
    body = re.sub(r"(?is)<(script|style|noscript|header|footer|nav)[^>]*>.*?</\1>", " ", h)
    paras = re.findall(r"(?is)<(?:p|article|div)[^>]*>(.*?)</(?:p|article|div)>", body)
    text = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(p)) for p in paras)
    text = re.sub(r"\s+", " ", text)
    # 날짜·장소 문장이 있는 구간만: 행사 단어 주변 3,000자
    i = max(0, min((text.find(w) for w in EVENT_WORDS if w in text), default=0) - 300)
    return (meta + " " + text[i:i + 3000]).strip()


# ── 추출 ──────────────────────────────────────────────────────
Q = r"['‘’\"“”「」『』<>〈〉《》]"


def event_name(title: str, text: str) -> str:
    cands = re.findall(r"['‘\"“「『<〈《]([^'’\"”」』>〉》]{3,40})['’\"”」』>〉》]", title + " " + text[:400])
    for c in cands:
        if any(w in c for w in EVENT_WORDS):
            return c.strip()
    m = re.search(r"((?:제\s?\d+\s?회\s?)?[가-힣A-Za-z0-9·&\s]{2,25}(?:축제|페스티벌|한마당|잔치|마켓|장터|음악회|축전))", title)
    return m.group(1).strip() if m else ""


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _year_for(month: int, pub: date) -> int:
    return pub.year + 1 if month < pub.month - 2 else pub.year


def event_dates(text: str, pub: date) -> tuple[date, date] | None:
    t = text
    # 11월 21일부터 12월 3일까지 / 11월 21~23일 / 11월 21일
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일\s*(?:\([^)]{1,3}\))?\s*(?:부터|~|-|∼)\s*(?:(\d{1,2})월\s*)?(\d{1,2})일", t)
    if m:
        m1, d1 = int(m.group(1)), int(m.group(2))
        m2, d2 = int(m.group(3) or m1), int(m.group(4))
        y1 = _year_for(m1, pub)
        s, e = _mk(y1, m1, d1), _mk(y1 + (1 if m2 < m1 else 0), m2, d2)
        if s and e:
            return s, e
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", t)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        s = _mk(_year_for(mo, pub), mo, d)
        if s:
            return s, s
    m = re.search(r"(?<!\d)(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*\((?:월|화|수|목|금|토|일)\)", t)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        s = _mk(_year_for(mo, pub), mo, d)
        if s:
            return s, s
    # 오는 21일 / 오는 21~23일 / 21일부터 23일까지
    m = re.search(r"오는\s*(\d{1,2})일\s*(?:\([^)]{1,3}\))?\s*(?:(?:부터|~|-|∼)\s*(\d{1,2})일)?", t) or \
        re.search(r"(?<![\d월])(\d{1,2})일\s*(?:\([^)]{1,3}\))?\s*(?:부터|~|-|∼)\s*(\d{1,2})일", t) or \
        re.search(r"(?<![\d월.:])(\d{1,2})\s*[~∼-]\s*(\d{1,2})일", t)
    if not m:  # 제목의 '21일 …' (단, '18일 밝혔다' 같은 보도일은 제외)
        m = re.search(r"(?<![\d월.])(\d{1,2})일(?!\s*(?:밝|발표|전했|말했))", t[:80])
    if m:
        d1 = int(m.group(1))
        d2 = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else d1
        y, mo = pub.year, pub.month
        if d1 < pub.day:  # 다음 달
            mo += 1
            if mo == 13:
                y, mo = y + 1, 1
        s = _mk(y, mo, d1)
        e = _mk(y, mo, d2) if d2 >= d1 else None
        if s:
            return s, (e or s)
    return None


def event_time(text: str) -> str:
    m = re.search(r"(\d{1,2}:\d{2})\s*(?:~|-|∼)\s*(\d{1,2}:\d{2})", text)
    if m:
        return f"{m.group(1)}~{m.group(2)}"
    m = re.search(r"(오전|오후)\s*(\d{1,2})시(?:\s*(\d{1,2})분)?\s*(?:부터|~)\s*(?:(오전|오후)\s*)?(\d{1,2})시", text)
    if m:
        return f"{m.group(1)} {m.group(2)}시{(' ' + m.group(3) + '분') if m.group(3) else ''} ~ {m.group(4) or ''}{' ' if m.group(4) else ''}{m.group(5)}시".replace("  ", " ")
    m = re.search(r"(오전|오후)\s*(\d{1,2})시(?:\s*(\d{1,2})분)?", text)
    if m:
        return f"{m.group(1)} {m.group(2)}시{(' ' + m.group(3) + '분') if m.group(3) else ''}"
    return ""


def event_place(text: str) -> str:
    """'…까지 전의청소년문화센터 잔디광장에서 … 연다' → '전의청소년문화센터 잔디광장'"""
    for m in re.finditer(r"에서", text):
        if not re.search(r"(열|연다|개최|진행|운영|펼쳐|마련|선보)", text[m.end():m.end() + 70]):
            continue
        take: list[str] = []
        for tok in reversed(text[max(0, m.start() - 50):m.start()].split()):
            if re.search(r"\d|부터|까지|오전|오후", tok) or (take and re.search(r"(은|는|을|를|와|과|도|며|고|해|서|에)$", tok)):
                break
            take.insert(0, tok.strip("'\"‘’“”,·"))
            if len(take) >= 4:
                break
        place = " ".join(t for t in take if t)
        if len(place) >= 2:
            return place[:30]
    return ""


def official_link(text: str, article_url: str) -> str:
    host = urlparse(article_url).netloc
    for u in re.findall(r"(?:https?://)?(?:www\.)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.(?:go\.kr|or\.kr|kr|com)(?:/[^\s\"'<>)]*)?", text):
        if host and host.split(".")[-2] in u:
            continue
        if any(x in u for x in ("news", "ytn", "kbs", "mbc", "sbs", "yna", "naver.com", "daum", "google", "facebook", "instagram", "youtube")):
            continue
        return u if u.startswith("http") else "https://" + u
    return ""


def kid_ok(title: str, text: str) -> bool:
    t = title + " " + text[:600]
    if any(b in title for b in BAD_WORDS):
        return False
    return any(w in t for w in KID_WORDS)


def norm(name: str) -> str:
    n = re.sub(r"\d{4}|제\s?\d+\s?회|[^0-9A-Za-z가-힣]", "", name)
    return n


# ── 메인 ──────────────────────────────────────────────────────
def collect(start: date, end: date, regions: list[str] | None = None) -> list[Event]:
    regions = regions or list(REGION_QUERY)
    cache: dict = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}

    # 1) RSS 검색
    jobs = [(reg, f"{REGION_QUERY[reg]} {kw}") for reg in regions for kw in KEYWORDS]
    found: dict[str, dict] = {}
    stat = {"bing": 0, "google": 0}

    def run(job):
        reg, q = job
        b, g = bing(q), google(q)
        return reg, b, g

    with ThreadPoolExecutor(max_workers=6) as ex:
        for reg, b, g in ex.map(run, jobs):
            stat["bing"] += len(b)
            stat["google"] += len(g)
            for it in b + g:
                key = it["link"]
                if not key or key in found:
                    continue
                it["region"] = reg
                found[key] = it

    # 2) 최근 기사만 + 제목 1차 필터
    today = datetime.now(KST).date()
    cands = []
    for it in found.values():
        try:
            pub = parsedate_to_datetime(it["pub"]).astimezone(KST).date()
        except Exception:  # noqa: BLE001
            pub = today
        if (today - pub).days > 21:
            continue
        if any(b in it["title"] for b in BAD_WORDS):
            continue
        if not any(w in it["title"] + it["desc"] for w in EVENT_WORDS):
            continue
        it["pubd"] = pub
        cands.append(it)

    # 3) 원문 읽어서 추출 (캐시 활용)
    need = [it for it in cands if it["link"] not in cache][:400]

    def extract(it):
        text = it["desc"] + " " + article_text(it["link"])
        name = event_name(it["title"], text)
        ds = event_dates(it["title"] + " " + text, it["pubd"]) if name else None
        return it["link"], {
            "name": name, "kid": kid_ok(it["title"], text),
            "start": ds[0].isoformat() if ds else "", "end": ds[1].isoformat() if ds else "",
            "time": event_time(text), "place": event_place(text),
            "official": official_link(text, it["link"]),
        }

    with ThreadPoolExecutor(max_workers=8) as ex:
        for link, res in ex.map(extract, need):
            cache[link] = res

    # 4) 행사로 묶기
    groups: dict[str, Event] = {}
    samples = []
    for it in cands:
        r = cache.get(it["link"])
        if not r or not r["name"] or not r["start"] or not r["kid"]:
            continue
        s, e = date.fromisoformat(r["start"]), date.fromisoformat(r["end"])
        if e < start or s > end or (e - s).days > 120:
            continue
        key = f"{it['region']}:{norm(r['name'])}"
        art = {"title": it["title"][:80], "url": it["link"], "source": it.get("source", "")[:20],
               "date": it["pubd"].isoformat()}
        ev = groups.get(key)
        if ev is None:
            ev = Event(source="news", title=r["name"], region=it["region"], start=s, end=e,
                       place=r["place"], genre="축제·행사 기사", kid_flag=False,
                       tags=[r["time"]] if r["time"] else [], link=r["official"] or it["link"],
                       official=r["official"])
            groups[key] = ev
            if len(samples) < 8:
                samples.append(f"{it['region']}|{r['name']}|{s}~{e}|{r['place']}|{r['time']}")
        if all(a["url"] != art["url"] for a in ev.articles):
            ev.articles.append(art)
        if not ev.place and r["place"]:
            ev.place = r["place"]
        if not ev.official and r["official"]:
            ev.official = ev.link = r["official"]
    for ev in groups.values():
        ev.articles = sorted(ev.articles, key=lambda a: a["date"], reverse=True)[:3]
        ev.tags = ev.tags + ["기사"]

    # 캐시는 최근 기사만 유지
    live = {it["link"] for it in cands}
    cache = {k: v for k, v in cache.items() if k in live}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    DEBUG.update({"rss": stat, "후보기사": len(cands), "새로읽음": len(need), "행사": len(groups), "예시": samples})
    return list(groups.values())
