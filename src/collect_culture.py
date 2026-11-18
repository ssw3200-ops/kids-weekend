"""한국문화정보원 한눈에보는문화정보 조회서비스 — 기간별 공연·전시 목록

- 공공데이터포털 '한국문화정보원_한눈에보는문화정보조회서비스' 활용신청 (무료, 개발계정 1만 건/일)
- ⚠ 오퍼레이션 경로(period2)와 응답 필드는 활용신청 후 '활용명세'에서 한 번 확인 필요.
  다르면 아래 URL / FIELD 매핑만 고치면 됩니다.
- 전국을 받고 응답의 area/place 필드로 시·도를 나눕니다.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import quote

from common import Event, city_of, http_get, parse_ymd, sido_of

URL = "https://apis.data.go.kr/B553457/cultureinfo/period2"

FIELD = {
    "title": "title", "start": "startDate", "end": "endDate", "place": "place",
    "area": "area", "sigungu": "sigungu", "genre": "realmName",
    "image": "thumbnail", "url": "url", "price": "price",
}


DEBUG = ""  # build.py가 상태에 같이 기록 (0건일 때 원인 파악용)


def collect(key: str, start: date, end: date) -> list[Event]:
    global DEBUG
    events: list[Event] = []
    raw, areas, msg, samples = 0, [], "", []
    page = 1
    total = None
    while page <= 100:  # 페이지 크기가 10으로 고정돼도 최대 1,000건까지 (하루 한도 1만 건 내)
        params = {
            "serviceKey": key,
            "from": start.strftime("%Y%m%d"),
            "to": end.strftime("%Y%m%d"),
            "cPage": page, "pageNo": page,
            "rows": 100, "numOfRows": 100,
        }
        content = http_get(URL, params).content
        root = ET.fromstring(content)
        rows = root.findall(".//item")
        msg = msg or (root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or "")
        if page == 1 and not rows:
            msg = msg or content[:150].decode("utf-8", "ignore")
        raw += len(rows)
        if total is None:
            t = root.findtext(".//totalCount")
            total = int(t) if t and t.strip().isdigit() else 0
        for it in rows:
            get = lambda k: (it.findtext(FIELD[k]) or "").strip()  # noqa: E731
            region = sido_of(get("area")) or sido_of(get("place"))
            if not region:
                if len(areas) < 5:
                    areas.append(f"{get('area')} {get('place')}".strip()[:20] or "(빈값)")
                continue
            s, e = parse_ymd(get("start")), parse_ymd(get("end"))
            if len(samples) < 3:
                samples.append(f"{get('title')[:12]}|{get('start')}~{get('end')}|{get('genre')}")
            if not s or not e:
                continue
            title = get("title")
            events.append(Event(
                source="culture",
                title=title,
                region=region, city=get("sigungu") if get("sigungu").endswith(("시", "군", "구")) else "",
                start=s, end=e,
                place=get("place"),
                price=get("price"),
                image=get("image").replace("http://", "https://"),
                link=get("url") or "https://search.naver.com/search.naver?query=" + quote(title),
                genre=get("genre") or "공연·전시",
            ))
        if not rows or raw >= (total or 0):
            break
        page += 1
    DEBUG = f"원본 {raw}/{total}건, 응답 '{msg[:60]}', 지역 못 찾은 예: {areas}, 샘플: {samples}"
    return events
