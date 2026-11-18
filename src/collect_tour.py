"""한국관광공사 TourAPI (국문 관광정보 서비스_GW) — 행사정보조회 searchFestival2

- 공공데이터포털 '한국관광공사_국문 관광정보 서비스_GW' 활용신청 → 일반 인증키(Decoding)
- areaCode는 폐기 예정이라 법정동 시도코드(lDongRegnCd) 사용
"""
from __future__ import annotations

from datetime import date, timedelta

from urllib.parse import quote

from common import Event, http_get, parse_ymd

URL = "https://apis.data.go.kr/B551011/KorService2/searchFestival2"


def _items(payload: dict) -> list[dict]:
    body = (payload.get("response") or {}).get("body") or {}
    items = body.get("items") or {}
    if not isinstance(items, dict):  # 결과 없으면 "" 로 옴
        return []
    item = items.get("item") or []
    return item if isinstance(item, list) else [item]


def collect(key: str, regions: list[dict], start: date, end: date) -> list[Event]:
    events: list[Event] = []
    for reg in regions:
        page = 1
        while True:
            params = {
                "serviceKey": key,
                "MobileOS": "ETC",
                "MobileApp": "kidsweekend",
                "_type": "json",
                "arrange": "C",
                "numOfRows": 100,
                "pageNo": page,
                # 주말 이전에 시작해서 진행 중인 행사까지 잡기 위해 60일 전부터 조회
                "eventStartDate": (start - timedelta(days=60)).strftime("%Y%m%d"),
                "lDongRegnCd": reg["tour_ldong"],
            }
            data = http_get(URL, params).json()
            rows = _items(data)
            for it in rows:
                s, e = parse_ymd(it.get("eventstartdate")), parse_ymd(it.get("eventenddate"))
                if not s or not e:
                    continue
                events.append(Event(
                    source="tour",
                    title=it.get("title", "").strip(),
                    region=reg["name"],
                    start=s, end=e,
                    place=(it.get("addr2") or "").strip(),
                    address=(it.get("addr1") or "").strip(),
                    image=(it.get("firstimage") or "").replace("http://", "https://"),
                    link="https://search.naver.com/search.naver?query=" + quote(it.get("title", "").strip()),
                    genre="축제·행사",
                ))
            total = int(((data.get("response") or {}).get("body") or {}).get("totalCount") or 0)
            if page * 100 >= total or not rows:
                break
            page += 1
    return events
