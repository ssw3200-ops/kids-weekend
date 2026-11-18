"""공공데이터포털 표준데이터 API (공공데이터포털 키 그대로 사용)

- 전국공연행사정보표준데이터  tn_pubr_public_pblprfr_event_info_api
- 전국문화축제표준데이터      tn_pubr_public_cltur_fstvl_api

표준데이터는 기간 검색이 안 돼서 전체를 페이지로 받아 기간·지역을 직접 거릅니다.
필드명이 기관마다 미묘하게 다를 수 있어 후보 이름을 여러 개 둡니다.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import quote

from common import Event, city_of, http_get, parse_ymd, sido_of

BASE = "https://api.data.go.kr/openapi/"

SPECS = {
    "std_event": {
        "path": "tn_pubr_public_pblprfr_event_info_api",
        "title": ["eventNm"], "start": ["eventStartDate"], "end": ["eventEndDate"],
        "place": ["opar"], "desc": ["eventCo"], "price": ["admfee", "chrgeInfo"],
        "age": ["entncAge"], "url": ["homepageUrl", "advantkInfo"], "genre_default": "공연",
        "time": ["eventStartTime"],
    },
    "std_festival": {
        "path": "tn_pubr_public_cltur_fstvl_api",
        "title": ["fstvlNm"], "start": ["fstvlStartDate"], "end": ["fstvlEndDate"],
        "place": ["opar"], "desc": ["fstvlCo"], "price": [], "age": [],
        "url": ["homepageUrl"], "genre_default": "축제", "time": [],
    },
}

DEBUG: dict[str, str] = {}


def _pick(it: dict, names: list[str]) -> str:
    for n in names:
        v = it.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def collect(name: str, key: str, start: date, end: date) -> list[Event]:
    spec = SPECS[name]
    events: list[Event] = []
    raw, total, keys, hmsg = 0, 0, [], ""
    page = 1
    while page <= 60:
        params = {"serviceKey": key, "pageNo": page, "numOfRows": 1000, "type": "json"}
        payload = http_get(BASE + spec["path"], params, timeout=40).json()
        resp = payload.get("response") or {}
        header = resp.get("header") or {}
        hmsg = hmsg or f"{header.get('resultCode')} {header.get('resultMsg')}"
        if page == 1 and not (resp.get("body") or {}).get("items"):
            hmsg = str(payload)[:200]
        if str(header.get("resultCode", "00")) not in ("00", "0"):
            if header.get("resultCode") == "03":  # NODATA
                break
            raise RuntimeError(f"{header.get('resultCode')} {header.get('resultMsg')}")
        body = resp.get("body") or {}
        items = body.get("items") or []
        if isinstance(items, dict):
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
        total = int(body.get("totalCount") or 0)
        raw += len(items)
        if items and not keys:
            keys = list(items[0].keys())[:30]
        for it in items:
            s, e = parse_ymd(_pick(it, spec["start"])), parse_ymd(_pick(it, spec["end"]))
            if not s or not e or s > end or e < start:
                continue
            addr = it.get("rdnmadr") or it.get("lnmadr") or ""
            region = sido_of(addr)
            if not region:
                continue
            title = _pick(it, spec["title"])
            if not title:
                continue
            price = _pick(it, spec["price"])
            if price.replace(" ", "") in ("0", "0원", "무료관람"):
                price = "무료"
            url = _pick(it, spec["url"])
            if url and not url.startswith("http"):
                url = "https://" + url
            desc = _pick(it, spec["desc"])
            tm = _pick(it, spec["time"])
            events.append(Event(
                source=name, title=title, region=region, city=city_of(addr),
                start=s, end=e, place=_pick(it, spec["place"]), address=addr,
                price=price[:60], age=_pick(it, spec["age"])[:40],
                link=url or "https://search.naver.com/search.naver?query=" + quote(title),
                genre=f"{spec['genre_default']} {desc[:40]}",
                tags=[f"{tm} 시작"] if tm else [],
            ))
        if not items or raw >= total:
            break
        page += 1
    DEBUG[name] = f"원본 {raw}/{total}건, 응답 {hmsg}" + ("" if events else f", 필드: {keys}")
    return events
