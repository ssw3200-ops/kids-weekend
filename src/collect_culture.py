"""한국문화정보원 한눈에보는문화정보 조회서비스 — 기간별 공연·전시 목록

- 공공데이터포털 '한국문화정보원_한눈에보는문화정보조회서비스' 활용신청 (무료, 개발계정 1만 건/일)
- ⚠ 오퍼레이션 경로(period2)와 응답 필드는 활용신청 후 '활용명세'에서 한 번 확인 필요.
  다르면 아래 URL / FIELD 매핑만 고치면 됩니다.
- 지역 파라미터 대신 응답의 area/place 필드로 거릅니다 (파라미터 명세가 바뀌어도 안전하게).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import quote

from common import Event, http_get, parse_ymd

URL = "https://apis.data.go.kr/B553457/cultureinfo/period2"

FIELD = {
    "title": "title", "start": "startDate", "end": "endDate", "place": "place",
    "area": "area", "sigungu": "sigungu", "genre": "realmName",
    "image": "thumbnail", "url": "url", "price": "price",
}


def collect(key: str, regions: list[dict], start: date, end: date) -> list[Event]:
    events: list[Event] = []
    page = 1
    while page <= 30:
        params = {
            "serviceKey": key,
            "from": start.strftime("%Y%m%d"),
            "to": end.strftime("%Y%m%d"),
            "cPage": page,
            "rows": 100,
        }
        root = ET.fromstring(http_get(URL, params).content)
        rows = root.findall(".//item")
        for it in rows:
            get = lambda k: (it.findtext(FIELD[k]) or "").strip()  # noqa: E731
            area_text = f"{get('area')} {get('sigungu')} {get('place')}"
            reg = next((r for r in regions if r["culture"] in area_text), None)
            if not reg:
                continue
            s, e = parse_ymd(get("start")), parse_ymd(get("end"))
            if not s or not e:
                continue
            title = get("title")
            events.append(Event(
                source="culture",
                title=title,
                region=reg["name"],
                start=s, end=e,
                place=get("place"),
                price=get("price"),
                image=get("image").replace("http://", "https://"),
                link=get("url") or "https://search.naver.com/search.naver?query=" + quote(title),
                genre=get("genre") or "공연·전시",
            ))
        if len(rows) < 100:
            break
        page += 1
    return events
