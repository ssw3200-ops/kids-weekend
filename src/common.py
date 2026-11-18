"""공통 유틸: 행사 데이터 구조, HTTP 호출, 날짜 계산"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))


@dataclass
class Event:
    source: str            # tour / kopis / culture / manual
    title: str
    region: str            # 세종 / 대전 ...
    start: date
    end: date
    place: str = ""
    address: str = ""
    price: str = ""
    image: str = ""
    link: str = ""
    genre: str = ""
    age: str = ""          # 관람 연령 원문
    kid_flag: bool = False # 소스가 아동용이라고 표시한 경우
    tags: list[str] = field(default_factory=list)
    score: int = 0

    @property
    def key(self) -> str:
        """중복 제거용 키: 공백·괄호·특수문자 제거한 제목 + 지역"""
        t = re.sub(r"\[.*?\]|\(.*?\)|<.*?>", "", self.title)
        t = re.sub(r"[^0-9A-Za-z가-힣]", "", t)
        return f"{self.region}:{t}"

    @property
    def is_free(self) -> bool:
        p = self.price.replace(" ", "")
        return ("무료" in p) or p in ("0", "0원")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        d["is_free"] = self.is_free
        return d


def today_kst() -> date:
    override = os.environ.get("TODAY")  # 테스트용: TODAY=2026-11-19
    if override:
        return date.fromisoformat(override)
    return datetime.now(KST).date()


def upcoming_weekend(base: date, include_friday: bool = True) -> tuple[date, date]:
    """base 기준 다가오는 주말 (토요일이 오늘이면 오늘 포함)"""
    days_to_sat = (5 - base.weekday()) % 7  # 일요일에 실행하면 다음 주 토요일
    sat = base + timedelta(days=days_to_sat)
    start = sat - timedelta(days=1) if include_friday else sat
    return start, sat + timedelta(days=1)


def overlaps(ev: Event, start: date, end: date) -> bool:
    return ev.start <= end and ev.end >= start


def parse_ymd(s: str) -> date | None:
    s = (s or "").strip().replace(".", "").replace("-", "")
    if len(s) >= 8 and s[:8].isdigit():
        try:
            return datetime.strptime(s[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def http_get(url: str, params: dict, tries: int = 3, timeout: int = 20) -> requests.Response:
    """공공 API는 가끔 타임아웃이 나서 재시도 포함"""
    last: Exception | None = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout,
                             headers={"User-Agent": "kids-weekend/1.0 (+github)"})
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"요청 실패: {url} ({last})")


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()
