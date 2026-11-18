"""한국관광공사 TourAPI (국문 관광정보 서비스_GW) — 행사정보조회 searchFestival2 (전국)

- 공공데이터포털 '한국관광공사_국문 관광정보 서비스_GW' 활용신청 → 일반 인증키(Decoding)
- 전국을 한 번에 받고 주소(addr1)로 시·도를 나눕니다.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from common import Event, city_of, http_get, parse_ymd, sido_of

URL = "https://apis.data.go.kr/B551011/KorService2/searchFestival2"


def _body(payload: dict) -> dict:
    return (payload.get("response") or {}).get("body") or {}


def _items(body: dict) -> list[dict]:
    items = body.get("items") or {}
    if not isinstance(items, dict):  # 결과 없으면 "" 로 옴
        return []
    item = items.get("item") or []
    return item if isinstance(item, list) else [item]


def collect(key: str, start: date, end: date) -> list[Event]:
    events: list[Event] = []
    page = 1
    while page <= 40:
        params = {
            "serviceKey": key, "MobileOS": "ETC", "MobileApp": "kidsweekend", "_type": "json",
            "arrange": "C", "numOfRows": 100, "pageNo": page,
            # 기간 전에 시작해서 진행 중인 행사까지 잡기 위해 60일 전부터 조회
            "eventStartDate": (start - timedelta(days=60)).strftime("%Y%m%d"),
        }
        body = _body(http_get(URL, params).json())
        rows = _items(body)
        for it in rows:
            s, e = parse_ymd(it.get("eventstartdate")), parse_ymd(it.get("eventenddate"))
            addr = (it.get("addr1") or "").strip()
            region = sido_of(addr)
            if not s or not e or not region:
                continue
            title = (it.get("title") or "").strip()
            events.append(Event(
                source="tour", title=title, region=region, city=city_of(addr),
                start=s, end=e,
                place=(it.get("addr2") or "").strip(), address=addr,
                image=(it.get("firstimage") or "").replace("http://", "https://"),
                link="https://search.naver.com/search.naver?query=" + quote(title),
                genre="축제·행사",
            ))
        total = int(body.get("totalCount") or 0)
        if not rows or page * 100 >= total:
            break
        page += 1
    return events
