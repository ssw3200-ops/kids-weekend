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
VERSION = 2  # 추출 규칙을 바꾸면 올리기 → 예전 캐시 결과는 다시 추출



# ── 지역 판별 (기사 속 시·군·구 → 시·도) ─────────────────────────
_SIGUNGU = {
    "서울": "종로구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구",
    "부산": "해운대구 수영구 사하구 사상구 금정구 연제구 동래구 부산진구 영도구 기장군",
    "대구": "수성구 달서구 달성군 군위군",
    "인천": "미추홀구 연수구 남동구 부평구 계양구 강화군 옹진군",
    "광주": "광산구",
    "대전": "유성구 대덕구",
    "울산": "울주군",
    "세종": "조치원읍 전의면 연기면 연동면 부강면 금남면 장군면 연서면 전동면 소정면",
    "경기": "수원시 성남시 의정부시 안양시 부천시 광명시 평택시 동두천시 안산시 고양시 과천시 구리시 남양주시 오산시 시흥시 군포시 의왕시 하남시 용인시 파주시 이천시 안성시 김포시 화성시 양주시 포천시 여주시 연천군 가평군 양평군",
    "강원": "춘천시 원주시 강릉시 동해시 태백시 속초시 삼척시 홍천군 횡성군 영월군 평창군 정선군 철원군 화천군 양구군 인제군 양양군",
    "충북": "청주시 충주시 제천시 보은군 옥천군 영동군 증평군 진천군 괴산군 음성군 단양군",
    "충남": "천안시 공주시 보령시 아산시 서산시 논산시 계룡시 당진시 금산군 부여군 서천군 청양군 홍성군 예산군 태안군",
    "전북": "전주시 군산시 익산시 정읍시 남원시 김제시 완주군 진안군 무주군 장수군 임실군 순창군 고창군 부안군",
    "전남": "목포시 여수시 순천시 나주시 광양시 담양군 곡성군 구례군 고흥군 보성군 화순군 장흥군 강진군 해남군 영암군 무안군 함평군 영광군 장성군 완도군 진도군 신안군",
    "경북": "포항시 경주시 김천시 안동시 구미시 영주시 영천시 상주시 문경시 경산시 의성군 청송군 영양군 영덕군 청도군 고령군 성주군 칠곡군 예천군 봉화군 울진군 울릉군",
    "경남": "창원시 진주시 통영시 사천시 김해시 밀양시 거제시 양산시 의령군 함안군 창녕군 남해군 하동군 산청군 함양군 거창군 합천군",
    "제주": "제주시 서귀포시",
}
_SIDO_WORDS = {"서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천", "광주광역시": "광주", "광주": "광주",
               "대전": "대전", "울산": "울산", "세종": "세종", "경기도": "경기", "경기": "경기", "강원": "강원",
               "충북": "충북", "충청북도": "충북", "충남": "충남", "충청남도": "충남", "전북": "전북", "전라북도": "전북",
               "전남": "전남", "전라남도": "전남", "경북": "경북", "경상북도": "경북", "경남": "경남", "경상남도": "경남",
               "제주": "제주"}
_PLACE2SIDO: dict[str, str] = {}
for _sido, _names in _SIGUNGU.items():
    for _n in _names.split():
        _PLACE2SIDO[_n] = _sido
        if len(_n) >= 3 and _n[-1] in "시군":  # '안산시' → '안산'도 (뒤에 공백·문장부호일 때)
            _PLACE2SIDO[_n[:-1]] = _sido
_PLACE_RE = re.compile(r"(?<![가-힣])(" + "|".join(sorted(list(_PLACE2SIDO) + list(_SIDO_WORDS), key=len, reverse=True)) + ")")


def detect_region(title: str, text: str) -> str:
    for src in (title, text[:300]):
        m = _PLACE_RE.search(src)
        if m:
            w = m.group(1)
            return _SIDO_WORDS.get(w) or _PLACE2SIDO.get(w, "")
    return ""

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


def gnews_resolve(url: str) -> str:
    """구글 뉴스 RSS 링크(news.google.com/rss/articles/…) → 언론사 원문 주소"""
    m = re.search(r"/articles/([^?/]+)", url)
    if not m:
        return ""
    aid = m.group(1)
    try:
        r = requests.get(f"https://news.google.com/articles/{aid}", headers=UA, timeout=12)
        sg = re.search(r'data-n-a-sg="([^"]+)"', r.text)
        ts = re.search(r'data-n-a-ts="([^"]+)"', r.text)
        if not (sg and ts):
            return ""
        inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                 f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{aid}",{ts.group(1)},"{sg.group(1)}"]')
        body = "f.req=" + quote(json.dumps([[["Fbv4je", inner, None, "generic"]]]))
        r2 = requests.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body, timeout=12,
                           headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        payload = json.loads(r2.text.split("\n\n", 1)[1])[:-2]
        return json.loads(payload[0][2])[1]
    except Exception:  # noqa: BLE001
        return ""


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


GENERIC = {"축제", "행사", "겨울축제", "가을축제", "봄축제", "여름축제", "문화축제", "가족축제", "지역축제",
           "체험행사", "어린이행사", "가족행사", "크리스마스축제", "빛축제", "마켓", "장터"}


def _clean_name(n: str) -> str:
    n = re.sub(r"(?:\d{1,2}월\s*)?\d{1,2}일(?:부터|까지)?", " ", n.strip())
    n = re.sub(r"\s+", " ", n)
    n = re.sub(r"^(?:오는|올해|올겨울|이번|내달|다음달)\s*", "", n)
    n = re.sub(r"\s*(?:개최|열려|연다|성황|팡파르|개막)$", "", n)
    return n.strip(" ,·-")


def event_name(title: str, text: str) -> str:
    cands = re.findall(r"['‘\"“「『<〈《]([^'’\"”」』>〉》]{3,40})['’\"”」』>〉》]", title + " " + text[:400])
    for c in cands:
        if any(w in c for w in EVENT_WORDS):
            n = _clean_name(c)
            if norm(n) not in GENERIC and len(norm(n)) >= 4:
                return n
    m = re.search(r"((?:제\s?\d+\s?회\s?)?[가-힣A-Za-z0-9·&]{2,15}(?:\s[가-힣A-Za-z0-9·&]{1,10}){0,2}\s?(?:축제|페스티벌|한마당|잔치|음악회|축전))", title)
    if m:
        n = _clean_name(m.group(1))
        if norm(n) not in GENERIC and len(norm(n)) >= 4:
            return n
    return ""


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
            if re.search(r"\d|부터|까지|오전|오후|개최|열려|밝혀|기자|뉴스|일보|신문|이코노미|타임즈|저널|미디어|투데이", tok) \
                    or re.search(r"(동안|간)$", tok) \
                    or (take and re.search(r"(은|는|을|를|와|과|도|며|고|해|서|에)$", tok)):
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
    cands.sort(key=lambda it: (not re.search(r"['‘\"“「<]", it["title"]), -it["pubd"].toordinal()))
    need = [it for it in cands if (cache.get(it["link"]) or {}).get("v") != VERSION][:250]

    def extract(it):
        real = it["link"]
        if "news.google.com" in real:
            real = gnews_resolve(real) or real
        text = it["desc"] + " " + article_text(real)
        name = event_name(it["title"], text)
        ds = event_dates(it["title"] + " " + text, it["pubd"]) if name else None
        return it["link"], {
            "v": VERSION, "url": real, "region": detect_region(it["title"], text),
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
        region = r.get("region") or ""
        if not region:
            continue
        key = f"{region}:{norm(r['name'])}"
        art = {"title": it["title"][:80], "url": r.get("url") or it["link"], "source": it.get("source", "")[:20],
               "date": it["pubd"].isoformat()}
        ev = groups.get(key)
        if ev is None:
            ev = Event(source="news", title=r["name"], region=region, start=s, end=e,
                       place=r["place"], genre="축제·행사 기사", kid_flag=False,
                       tags=[r["time"]] if r["time"] else [], link=r["official"] or art["url"],
                       official=r["official"])
            groups[key] = ev
            if len(samples) < 8:
                samples.append(f"{region}|{r['name']}|{s}~{e}|{r['place']}|{r['time']}|{'원문' if 'google' not in art['url'] else '구글'}")
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
