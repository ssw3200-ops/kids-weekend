"""KOPIS 공연예술통합전산망 — 공연목록 조회 (pblprfr)

- kopis.or.kr > 공연예술통합전산망 OPEN API 에서 서비스키 발급 (무료)
- kidstate=Y : 아동 공연만
- 응답은 XML
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

from common import Event, http_get, parse_ymd

URL = "https://www.kopis.or.kr/openApi/restful/pblprfr"
DETAIL = "https://www.kopis.or.kr/por/db/pblprfr/pblprfrView.do?menuId=MNU_00020&mt20Id="


def _txt(node: ET.Element, tag: str) -> str:
    v = node.findtext(tag)
    return (v or "").strip()


def collect(key: str, regions: list[dict], start: date, end: date) -> list[Event]:
    events: list[Event] = []
    for reg in regions:
        page = 1
        while page <= 5:  # 지역당 최대 500건이면 충분
            params = {
                "service": key,
                "stdate": start.strftime("%Y%m%d"),
                "eddate": end.strftime("%Y%m%d"),
                "cpage": page,
                "rows": 100,
                "signgucode": reg["kopis"],
                "kidstate": "Y",
            }
            root = ET.fromstring(http_get(URL, params).content)
            rows = root.findall("db")
            for db in rows:
                s, e = parse_ymd(_txt(db, "prfpdfrom")), parse_ymd(_txt(db, "prfpdto"))
                if not s or not e:
                    continue
                pid = _txt(db, "mt20id")
                events.append(Event(
                    source="kopis",
                    title=_txt(db, "prfnm"),
                    region=reg["name"],
                    start=s, end=e,
                    place=_txt(db, "fcltynm"),
                    image=_txt(db, "poster").replace("http://", "https://"),
                    link=DETAIL + pid if pid else "",
                    genre=_txt(db, "genrenm") or "공연",
                    kid_flag=True,
                ))
            if len(rows) < 100:
                break
            page += 1
    return events
