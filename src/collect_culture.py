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


# 페이지 파라미터 이름이 명세마다 달라서 실제로 다음 페이지가 나오는 조합을 자동으로 찾습니다.
PAGING = [("PageNo", "numOfrows"), ("pageNo", "numOfRows"), ("cPage", "rows"), ("page", "perPage")]


def _fetch(key: str, start: date, end: date, pk: str, rk: str, page: int):
    params = {"serviceKey": key, "from": start.strftime("%Y%m%d"), "to": end.strftime("%Y%m%d"),
              pk: page, rk: 100}
    content = http_get(URL, params).content
    root = ET.fromstring(content)
    return root, root.findall(".//item"), content


def _sig(rows) -> tuple:
    return tuple((r.findtext("seq") or r.findtext("title") or "") for r in rows[:3])


def collect(key: str, start: date, end: date) -> list[Event]:
    global DEBUG
    events: list[Event] = []
    seen: set[str] = set()
    raw, areas, msg = 0, [], ""

    # 1) 페이지 파라미터 조합 찾기: 1쪽과 2쪽 결과가 다르면 성공
    chosen, first = None, None
    for pk, rk in PAGING:
        root1, rows1, content = _fetch(key, start, end, pk, rk, 1)
        if first is None:
            first = (root1, rows1)
            msg = root1.findtext(".//resultMsg") or content[:120].decode("utf-8", "ignore")
        if not rows1:
            continue
        _, rows2, _ = _fetch(key, start, end, pk, rk, 2)
        if not rows2 or _sig(rows2) != _sig(rows1):
            chosen = (pk, rk, root1, rows1)
            break
    if chosen is None:  # 다 실패하면 1쪽만 사용
        pk, rk = PAGING[0]
        root, rows = first if first else (None, [])
    else:
        pk, rk, root, rows = chosen
    t = root.findtext(".//totalCount") if root is not None else None
    total = int(t) if t and t.strip().isdigit() else 0

    page = 1
    while True:
        new = 0
        for it in rows:
            get = lambda k: (it.findtext(FIELD[k]) or "").strip()  # noqa: E731
            uid = get("title") + get("start") + get("place")
            if uid in seen:
                continue
            seen.add(uid)
            new += 1
            raw += 1
            region = sido_of(get("area")) or sido_of(get("place"))
            if not region:
                if len(areas) < 5:
                    areas.append(f"{get('area')} {get('place')}".strip()[:20] or "(빈값)")
                continue
            s, e = parse_ymd(get("start")), parse_ymd(get("end"))
            if not s or not e:
                continue
            title = get("title")
            sg = get("sigungu")
            events.append(Event(
                source="culture", title=title, region=region,
                city=sg if sg.endswith(("시", "군", "구")) else "",
                start=s, end=e, place=get("place"), price=get("price"),
                image=get("image").replace("http://", "https://"),
                link=get("url") or "https://search.naver.com/search.naver?query=" + quote(title),
                genre=get("genre") or "공연·전시",
            ))
        if chosen is None or not rows or new == 0 or raw >= total or page >= 120:
            break
        page += 1
        _, rows, _ = _fetch(key, start, end, pk, rk, page)
    DEBUG = f"페이지키 {pk if chosen else '없음'}, 원본 {raw}/{total}건, 응답 '{msg[:40]}'" + (
        f", 지역 못 찾음: {areas}" if areas else "")
    return events
