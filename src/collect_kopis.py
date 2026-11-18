"""KOPIS 공연예술통합전산망 — 아동 공연 목록(pblprfr, 전국) + 상세

- kopis.or.kr 고객지원 > OPEN API 에서 서비스키 발급 (무료)
- kidstate=Y : 아동 공연만, 응답은 XML
- 상세(가격·연령·시간·예매처)는 docs/cache/kopis_detail.json 에 캐시해서
  다음 주 실행 때 같은 공연은 다시 부르지 않습니다.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from common import Event, http_get, parse_ymd, sido_of

URL = "https://www.kopis.or.kr/openApi/restful/pblprfr"
DETAIL = "https://www.kopis.or.kr/por/db/pblprfr/pblprfrView.do?menuId=MNU_00020&mt20Id="
CACHE = Path(__file__).resolve().parent.parent / "docs" / "cache" / "kopis_detail.json"


def _txt(node: ET.Element, tag: str) -> str:
    return (node.findtext(tag) or "").strip()


def _clean_title(t: str) -> str:
    """'정글북 [대전]' → '정글북', 끝의 '(11.21)' 같은 날짜 꼬리도 제거"""
    t = re.sub(r"\s*\[[^\]]*\]\s*", " ", t)
    t = re.sub(r"\s*\(\d{1,2}\.\d{1,2}\)\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _detail(key: str, pid: str) -> dict:
    try:
        root = ET.fromstring(http_get(f"{URL}/{pid}", {"service": key}, tries=2).content)
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


def collect(key: str, start: date, end: date) -> list[Event]:
    rows_all: list[ET.Element] = []
    page = 1
    while page <= 30:
        params = {"service": key, "stdate": start.strftime("%Y%m%d"), "eddate": end.strftime("%Y%m%d"),
                  "cpage": page, "rows": 100, "kidstate": "Y"}
        rows = ET.fromstring(http_get(URL, params).content).findall("db")
        rows_all += rows
        if len(rows) < 100:
            break
        page += 1

    cache: dict = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    live = {_txt(db, "mt20id") for db in rows_all} - {""}
    need = [p for p in live if p not in cache]
    with ThreadPoolExecutor(max_workers=4) as ex:  # 서버에 무리 없게 4개씩
        for pid, det in zip(need, ex.map(lambda p: _detail(key, p), need)):
            if det:
                cache[pid] = det
    cache = {k: v for k, v in cache.items() if k in live}  # 끝난 공연은 캐시에서 정리
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    events: list[Event] = []
    for db in rows_all:
        s, e = parse_ymd(_txt(db, "prfpdfrom")), parse_ymd(_txt(db, "prfpdto"))
        region = sido_of(_txt(db, "area"))
        if not s or not e or not region:
            continue
        pid = _txt(db, "mt20id")
        det = cache.get(pid, {})
        price = det.get("price", "")
        events.append(Event(
            source="kopis", title=_clean_title(_txt(db, "prfnm")), region=region,
            start=s, end=e, place=_txt(db, "fcltynm"),
            price=price[:60] + ("…" if len(price) > 60 else ""),
            age=det.get("age", ""),
            tags=[det["time"][:40]] if det.get("time") else [],
            image=_txt(db, "poster").replace("http://", "https://"),
            link=det.get("book") or (DETAIL + pid if pid else ""),
            genre=_txt(db, "genrenm") or "공연", kid_flag=True,
        ))
    return events
