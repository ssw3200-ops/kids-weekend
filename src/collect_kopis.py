"""KOPIS 공연예술통합전산망 — 공연목록 조회 (pblprfr)

- kopis.or.kr > 공연예술통합전산망 OPEN API 에서 서비스키 발급 (무료)
- kidstate=Y : 아동 공연만
- 응답은 XML
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date

from common import Event, http_get, parse_ymd

URL = "https://www.kopis.or.kr/openApi/restful/pblprfr"
DETAIL = "https://www.kopis.or.kr/por/db/pblprfr/pblprfrView.do?menuId=MNU_00020&mt20Id="


def _txt(node: ET.Element, tag: str) -> str:
    v = node.findtext(tag)
    return (v or "").strip()


def _clean_title(t: str) -> str:
    """'정글북 [대전]' → '정글북', '(11.21)' 같은 날짜 꼬리도 제거"""
    t = re.sub(r"\s*\[[^\]]*\]\s*", " ", t)
    t = re.sub(r"\s*\(\d{1,2}\.\d{1,2}\)\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _detail(key: str, pid: str) -> dict:
    """공연 상세: 가격(pcseguidance), 관람연령(prfage), 예매처(relateurl)"""
    try:
        root = ET.fromstring(http_get(f"{URL}/{pid}", {"service": key}).content)
        db = root.find("db")
        if db is None:
            return {}
        rel = db.find(".//relate/relateurl")
        return {
            "price": _txt(db, "pcseguidance"),
            "age": _txt(db, "prfage"),
            "time": _txt(db, "dtguidance"),
            "book": (rel.text or "").strip() if rel is not None else "",
        }
    except Exception:  # noqa: BLE001 — 상세 실패해도 목록 정보로 진행
        return {}


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
                det = _detail(key, pid) if pid and s <= end and e >= start else {}
                price = det.get("price", "")
                if len(price) > 60:
                    price = price[:60] + "…"
                events.append(Event(
                    source="kopis",
                    title=_clean_title(_txt(db, "prfnm")),
                    price=price,
                    age=det.get("age", ""),
                    tags=[det["time"][:40]] if det.get("time") else [],
                    region=reg["name"],
                    start=s, end=e,
                    place=_txt(db, "fcltynm"),
                    image=_txt(db, "poster").replace("http://", "https://"),
                    link=det.get("book") or (DETAIL + pid if pid else ""),
                    genre=_txt(db, "genrenm") or "공연",
                    kid_flag=True,
                ))
            if len(rows) < 100:
                break
            page += 1
    return events
