"""기관 홈페이지·예약 페이지에서 아이 행사 수집 (키 없음)

공공 API에는 공연이 대부분이라, 과학관·미술관·시청·예약 시스템에 올라오는
체험·교육·시즌 행사를 직접 읽어옵니다. 읽을 곳은 sources.yaml 에서 관리합니다.

- links : 링크 글자 속 날짜로 행사를 찾음 (메인 화면 행사 배너 등)
- table : 표 한 줄 = 행사 1개 (대전 OK예약서비스)
- items : 목록 한 칸 = 행사 1개 (미술관 교육 목록)
- rss   : 블로그 RSS
페이지 글자(행사명·날짜·장소·요금)만 쓰고 사진·본문은 저장하지 않습니다.
"""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

from common import Event, city_of, today_kst

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
DEBUG: dict[str, str] = {}

# ── 날짜 ───────────────────────────────────────────────────────
_WD = r"(?:\s*\(\s*[월화수목금토일]\s*\))?"
# 2026. 11. 21. / 2026-11-21 / 2026.11.21 / 2026년 11월 21일 / '26.12.9
_FULL = r"(?P<y>20\d{2}|'\d{2})\s*[.\-/년]\s*(?P<m>\d{1,2})\s*[.\-/월]\s*(?P<d>\d{1,2})\s*[.일]?" + _WD
# 11. 21.(토) / 11월 21일 / 12.25 (요일이나 '일'이 붙거나, 범위 뒤쪽일 때만)
_SHORT = r"(?P<sm>\d{1,2})\s*(?:월\s*(?P<d1>\d{1,2})\s*일|\.\s*(?P<d2>\d{1,2})\s*\.?)" + _WD
_TOKEN = re.compile(f"(?:{_FULL})|(?:{_SHORT})")
_SEP = re.compile(r"^\s*(?:\d{1,2}:\d{2}\s*)?(?:~|∼|－|–|-|부터)\s*")


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _guess_year(m: int, base: date) -> int:
    """연도가 없으면 오늘 기준으로 가까운 쪽 (11월에 '1월'이면 내년)"""
    if m < base.month - 4:
        return base.year + 1
    if m > base.month + 7:
        return base.year - 1
    return base.year


def _tokens(text: str, base: date) -> list[tuple[int, int, date, bool]]:
    """(시작위치, 끝위치, 날짜, 연도있음)"""
    out = []
    for m in _TOKEN.finditer(text):
        g = m.groupdict()
        if g.get("y"):
            y = g["y"]
            y = 2000 + int(y[1:]) if y.startswith("'") else int(y)
            d = _mk(y, int(g["m"]), int(g["d"]))
            if d:
                out.append((m.start(), m.end(), d, True))
            continue
        mo = int(g["sm"])
        dd = g.get("d1") or g.get("d2")
        if not dd:
            continue
        raw = m.group(0)
        # '1.5' 같은 숫자, 시각(14.00) 오인 방지: 요일/일/점 마침이 있어야 함
        if not (re.search(r"[월일)]", raw) or raw.rstrip().endswith(".")):
            continue
        d = _mk(_guess_year(mo, base), mo, int(dd))
        if d:
            out.append((m.start(), m.end(), d, False))
    return out


def find_period(text: str, base: date) -> tuple[date, date] | None:
    """글 속 첫 날짜(범위)를 행사 기간으로. '2026. 11. 17.(화) ~ 11. 28.(토)' 처리"""
    toks = _tokens(text, base)
    if not toks:
        return None
    s0, e0, start, _ = toks[0]
    end = start
    if len(toks) > 1:
        s1, e1, nxt, has_y = toks[1]
        if _SEP.match(text[e0:s1]) and len(text[e0:s1]) <= 12:
            if not has_y and nxt < start:  # 12.20 ~ 1.10
                nxt = _mk(nxt.year + 1, nxt.month, nxt.day) or nxt
            if nxt >= start:
                end = nxt
    # 범위 뒤쪽만 '~ 11.30'처럼 짧은 경우(앞에 연도 없는 MM.DD)
    m = re.match(r"\s*(?:~|∼|-)\s*(\d{1,2})\s*\.\s*(\d{1,2})(?!\d)", text[e0:e0 + 14])
    if end == start and m:
        mo, d = int(m.group(1)), int(m.group(2))
        cand = _mk(start.year + (1 if mo < start.month else 0), mo, d)
        if cand and cand >= start:
            end = cand
    return start, end


def short_range(text: str, base: date) -> tuple[date, date] | None:
    """'10.21 ~ 01.31' (연도·요일 없음) 형식"""
    m = re.search(r"(?<![\d.])(\d{1,2})\.(\d{2})\s*~\s*(\d{1,2})\.(\d{2})(?![\d.])", text)
    if not m:
        return None
    m1, d1, m2, d2 = map(int, m.groups())
    s = _mk(_guess_year(m1, base), m1, d1)
    if not s:
        return None
    e = _mk(s.year + (1 if m2 < m1 else 0), m2, d2)
    return (s, e) if e and e >= s else None


# ── 공통 ───────────────────────────────────────────────────────
def _clean(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _title_from(text: str) -> str:
    """링크 글자에서 행사명: 날짜·장소 앞부분, 앞쪽 분류 꼬리표 제거"""
    t = text
    t = re.sub(r"^(?:(?:NEW|행사|특별전|교육|공지|알림|긴급|프로그램|전시|진행예정|진행중|접수중|접수예정)\s+)+", "", t)
    t = re.sub(r"\S*(?:안내\s*)?포스터로\s*자세한\s*(?:내용|사항)은\s*본\S*\s*참조\S*\s*", "", t)
    cut = _TOKEN.search(t)
    if cut and cut.start() > 4:
        t = t[:cut.start()]
    t = re.split(r"\s[,|]\s|,\s*$", t)[0]
    t = t.strip(" ,·-|:")
    t = re.sub(r"\s*(?:개최|운영)?\s*(?:및\s*\S+\s*)?안내$", "", t).strip(" ,")
    return t[:60]


def _price_from(text: str) -> str:
    if "무료" in text:
        return "무료"
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원", text)
    return f"{m.group(0)}" if m else ""


def _get(url: str, data: dict | None = None) -> str:
    last = None
    for i in range(2):
        try:
            if data is None:
                r = requests.get(url, headers=UA, timeout=20)
            else:
                r = requests.post(url, headers=UA, data=data, timeout=20)
            r.raise_for_status()
            if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                r.encoding = r.apparent_encoding
            return r.text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"접속 실패: {type(last).__name__}")


def _skip(title: str, src: dict, common: list[str]) -> bool:
    words = list(common) + list(src.get("skip", []))
    return any(w in title for w in words)


def _mk_event(src: dict, title: str, period: tuple[date, date], place: str = "", price: str = "",
              link: str = "", extra: str = "") -> Event:
    addr = src.get("address", "")
    ev = Event(source="org", title=title, region=src["region"], start=period[0], end=period[1],
               place=place or src.get("place", ""), address=addr, price=price,
               link=link or src["url"], genre=f"{src.get('genre', '')} {extra}".strip(),
               kid_flag=bool(src.get("kid")), tags=[src["name"]])
    ev.city = city_of(addr)
    return ev


# ── 형식별 파서 ────────────────────────────────────────────────
def parse_links(doc: str, src: dict, base: date) -> list[Event]:
    soup = BeautifulSoup(doc, "html.parser")
    pat = re.compile(src.get("link_pattern", "."))
    out, seen = [], set()
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        if not pat.search(href):
            continue
        text = _clean(a.get_text(" "))
        if len(text) < 6:
            continue
        period = find_period(text, base)
        if not period:
            continue
        if re.match(r"^(?:\S+\s+)?(?:종료|마감)\s", text):  # '종료 공연명 …'
            continue
        title = _title_from(text)
        who = ""
        wm = re.search(r"\s(가족|어린이|영유아|유아|초등|단체|성인|청소년|전체)$", title)
        if wm:  # 국립어린이박물관: '스타가 떴다! 가족'
            who = wm.group(1)
            title = title[:wm.start()].strip()
            if who in ("단체", "성인", "청소년"):
                continue
        if len(title) < 3 or title in seen:
            continue
        seen.add(title)
        age = ""
        am = re.search(r",?\s*(\d{1,2}\s*세\s*이상|초등학생\s*이상|초등\s*\d\s*~\s*\d\s*학년|전\s*연령)(?:\s*~\s*성인)?", title)
        if am:  # '6세 이상~성인' → 연령은 따로 ('성인' 때문에 제외되지 않게)
            age = am.group(1)
            title = (title[:am.start()] + title[am.end():]).strip(" ,")
        link = urljoin(src["url"], href) if not href.startswith("javascript") else src["url"]
        place = ""
        m = re.search(r"(국립\S+관|\S+(?:센터|도서관|미술관|박물관|공원|아트센터|홀|광장))(?:\s\S+관)?", text[len(title):])
        if m and not src.get("place"):
            place = m.group(0)[:30]
        ev = _mk_event(src, title, period, place=place, price=_price_from(text), link=link)
        ev.age = age or (f"{who} 대상" if who else "")
        out.append(ev)
    return out


def parse_table(doc: str, src: dict, base: date) -> list[Event]:
    soup = BeautifulSoup(doc, "html.parser")
    cols = src.get("columns", {})
    out = []
    for table in soup.find_all("table"):
        heads = [_clean(th.get_text(" ")) for th in table.find_all("th")]
        if not heads or cols.get("title") not in heads:
            continue
        idx = {k: heads.index(v) for k, v in cols.items() if v in heads}
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < len(heads) - 1:
                continue
            cell = lambda k: _clean(tds[idx[k]].get_text(" ")) if k in idx and idx[k] < len(tds) else ""  # noqa: E731
            title = cell("title")
            if not title:
                continue
            status = cell("status")
            if any(s in status for s in src.get("skip_status", [])):
                continue
            period = find_period(cell("period"), base)
            if not period:
                continue
            days = re.search(r"\(([월화수목금토일,·\s]+)\)", cell("period"))
            extra = f"운영요일 {days.group(1).replace(' ', '')}" if days else ""
            place = cell("place")
            if place and place.split()[0] not in title:  # '아동반(10~12월)' → '대전목재문화체험장 아동반(10~12월)'
                title = f"{place} {title}"
            ev = _mk_event(src, title, period, place=place, price=cell("price"), extra=extra)
            if extra:
                ev.tags.append(extra)
            if status:
                ev.tags.append(status)
            out.append(ev)
        break
    return out


def parse_items(doc: str, src: dict, base: date) -> list[Event]:
    soup = BeautifulSoup(doc, "html.parser")
    out = []
    for li in soup.find_all("li"):
        strong = li.find("strong")
        text = _clean(li.get_text(" "))
        if not strong or "기 간" not in text and "기간" not in text:
            continue
        title = _clean(strong.get_text(" "))
        m = re.search(r"기\s?간\s*(.{0,40})", text)
        period = find_period(m.group(1), base) if m else None
        if not title or not period:
            continue
        pm = re.search(r"장\s?소\s*([^\s].{0,25}?)(?:\s(?:종료|교육중|접수중|접수예정|진행중)|$)", text)
        place = pm.group(1).strip() if pm else ""
        if place and not any(k in place for k in ("미술관", "센터", "도서관", "박물관", "관")):
            place = f"{src.get('place', '')} {place}".strip()
        a = li.find("a")
        href = (a.get("href") if a else "") or ""
        link = urljoin(src["url"], href) if href and not href.startswith(("javascript", "#")) else src["url"]
        out.append(_mk_event(src, title, period, place=place, price=_price_from(text), link=link))
    return out


def parse_rss(doc: str, src: dict, base: date) -> list[Event]:
    try:
        root = ET.fromstring(doc.encode("utf-8") if isinstance(doc, str) else doc)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        title = _clean(it.findtext("title") or "")
        desc = _clean(re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or "")))[:500]
        period = find_period(title + " " + desc, base)
        if not period or period[1] < base:  # 이미 지난 행사 후기 글은 제외
            continue
        if any(w in title for w in ("후기", "다녀", "다녀온", "풍경", "기자단 모집")):
            continue
        name = re.sub(r"^\[[^\]]*\]\s*", "", title)
        name = re.sub(r"\([^)]*기자\)$", "", name).strip()
        out.append(_mk_event(src, name[:60], period, link=(it.findtext("link") or src["url"]).strip(),
                             price=_price_from(desc)))
    return out


PARSERS = {"links": parse_links, "table": parse_table, "items": parse_items, "rss": parse_rss}


PAGE_FIELDS = ["pageIndex", "currentPageNo", "pageNo", "page", "cpage", "curPage", "nowPage"]


def _form_fields(doc: str) -> tuple[str, dict, list[str]]:
    """목록 페이지의 검색 form(숨은 값 포함)과 페이지 번호 칸 이름 후보"""
    soup = BeautifulSoup(doc, "html.parser")
    best, fields = "", {}
    for form in soup.find_all("form"):
        vals = {i.get("name"): i.get("value", "") for i in form.find_all("input") if i.get("name")}
        for sel in form.find_all("select"):
            if sel.get("name"):
                opt = sel.find("option", selected=True) or sel.find("option")
                vals[sel["name"]] = (opt.get("value", "") if opt else "")
        if len(vals) > len(fields):
            best, fields = form.get("action") or "", vals
    scripts = " ".join(sc.get_text() for sc in soup.find_all("script"))
    guess = re.findall(r"(?:name=['\"]?|\.|getElementById\(['\"])(\w*[pP]age\w*)['\"]?\]?\)?\.val(?:ue)?\s*(?:=|\()", scripts)
    names = [n for n in dict.fromkeys(guess + [k for k in fields if "age" in k.lower()] + PAGE_FIELDS)]
    return best, fields, names


def fetch_pages(src: dict) -> list[str]:
    """table 은 여러 페이지: 검색 form 을 그대로 POST 하면서 페이지 칸만 바꿈 (같은 내용이면 멈춤)"""
    sess = requests.Session()
    sess.headers.update(UA)

    def get(url: str, data: dict | None = None) -> str:
        last = None
        for i in range(2):
            try:
                r = sess.get(url, timeout=20) if data is None else \
                    sess.post(url, data=data, timeout=20, headers={"Referer": src["url"]})
                r.raise_for_status()
                if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                    r.encoding = r.apparent_encoding
                return r.text
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (i + 1))
        raise RuntimeError(f"접속 실패: {type(last).__name__}")

    first = get(src["url"])
    docs = [first]
    pages = int(src.get("pages", 1))
    if src.get("type") != "table" or pages <= 1:
        return docs
    sig = lambda d: re.sub(r"\s+", "", " ".join(td.get_text() for td in BeautifulSoup(d, "html.parser").find_all("td")))[:4000]  # noqa: E731
    seen = {sig(first)}
    action, fields, names = _form_fields(first)
    post_url = urljoin(src["url"], action) if action and not action.startswith("javascript") else src["url"].split("?")[0]
    base_data = {**_qs(src["url"]), **fields}
    sep = "&" if "?" in src["url"] else "?"
    works: tuple[str, str] | None = None  # (방식, 칸이름) — 2쪽에서 찾은 방법을 계속 씀
    for p in range(2, pages + 1):
        got = None
        tries = [works] if works else [(k, n) for n in names for k in ("post", "get")]
        for kind, n in tries:
            try:
                d = get(post_url, {**base_data, n: str(p)}) if kind == "post" else \
                    get(f"{src['url']}{sep}{n}={p}")
            except RuntimeError:
                continue
            if sig(d) not in seen:
                got, works = d, (kind, n)
                break
        if not got:
            break
        seen.add(sig(got))
        docs.append(got)
    if works:
        DEBUG[f"{src['name']} 쪽넘김"] = f"{works[0]} {works[1]}"
    return docs


def _qs(url: str) -> dict:
    if "?" not in url:
        return {}
    return dict(kv.split("=", 1) for kv in url.split("?", 1)[1].split("&") if "=" in kv)


# ── 메인 ──────────────────────────────────────────────────────
def collect(start: date, end: date, path: Path | None = None) -> list[Event]:
    cfg = yaml.safe_load((path or ROOT / "sources.yaml").read_text(encoding="utf-8")) or {}
    common = cfg.get("common_skip", [])
    base = today_kst()
    out: list[Event] = []
    for src in cfg.get("sources", []):
        if src.get("enabled", True) is False:
            continue
        name = src["name"]
        try:
            docs = fetch_pages(src)
            got: list[Event] = []
            for d in docs:
                got += PARSERS[src["type"]](d, src, base)
            raw = len(got)
            if raw == 0:  # 왜 0건인지 볼 수 있게 받은 페이지 앞부분 저장 (공개 홈페이지 글자만)
                dbg = ROOT / "docs" / "cache" / "org_debug"
                dbg.mkdir(parents=True, exist_ok=True)
                slug = re.sub(r"[^0-9A-Za-z가-힣]", "_", name)
                (dbg / f"{slug}.html").write_text(docs[0][:60000], encoding="utf-8")
            uniq: dict[str, Event] = {}
            for ev in got:
                if _skip(ev.title, src, common):
                    continue
                if ev.end < start or ev.start > end or (ev.end - ev.start).days > 120:
                    continue
                uniq.setdefault(ev.title, ev)
            out += uniq.values()
            DEBUG[name] = f"{len(uniq)}건 (읽은 {raw}건, {len(docs)}쪽)"
        except Exception as e:  # noqa: BLE001
            DEBUG[name] = f"실패: {e}"[:120]
    return out


def sample(base: date) -> list[Event]:
    """--sample 미리보기용: tests/fixtures/org 의 저장된 페이지로 파서 확인"""
    fx = ROOT / "tests" / "fixtures" / "org"
    demo = [
        ({"name": "국립중앙과학관", "region": "대전", "type": "links", "url": "https://www.science.go.kr/mps/index.do",
          "link_pattern": "moveBbsNttDetail.do", "place": "국립중앙과학관",
          "address": "대전광역시 유성구 대덕대로 481", "genre": "과학 체험", "kid": True}, "science.html"),
        ({"name": "대전 OK예약 체험", "region": "대전", "type": "table",
          "url": "https://www.daejeon.go.kr/okr2019/expRsvtList.do?menuSeq=8201",
          "columns": {"place": "시설명", "title": "예약명", "period": "이용기간", "price": "수강료", "status": "접수상태"},
          "skip_status": ["접수종료", "인원마감"], "genre": "체험", "kid": True}, "okr.html"),
        ({"name": "대전시립미술관 어린이·가족", "region": "대전", "type": "items",
          "url": "https://www.daejeon.go.kr/dma/DmaEduList.do?category=2&menuSeq=6089", "place": "대전시립미술관",
          "address": "대전광역시 서구 둔산대로 155", "genre": "미술 체험", "kid": True}, "dma.html"),
        ({"name": "세종시 공식 블로그", "region": "세종", "type": "rss",
          "url": "https://rss.blog.naver.com/sejong_story.xml", "genre": "행사"}, "blog.xml"),
    ]
    out: list[Event] = []
    for src, f in demo:
        p = fx / f
        if p.exists():
            out += PARSERS[src["type"]](p.read_text(encoding="utf-8"), src, base)
    common = (yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8")) or {}).get("common_skip", [])
    return [e for e in out if not _skip(e.title, {}, common)]
