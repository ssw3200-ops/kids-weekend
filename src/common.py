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
    region: str            # 시·도 짧은 이름 (서울, 세종, 경기 ...)
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
    city: str = ""         # 시·군·구 (주소에서 추출, 없으면 빈값)
    category: str = ""     # 화면 분야 (분류는 category_of)
    articles: list[dict] = field(default_factory=list)  # 기사 수집: [{title, url, source, date}]
    official: str = ""     # 기사에서 찾은 공식 페이지

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
        d["news"] = self.source == "news"
        if not self.articles:
            d.pop("articles")
        if not self.official:
            d.pop("official")
        for k in ("source", "kid_flag", "score", "genre"):  # 화면에 안 쓰는 값은 빼서 용량 절약
            d.pop(k, None)
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


# ── 지역 정규화 ─────────────────────────────────────────────
SIDO = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
        "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
_SIDO_PREFIX = [
    ("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"), ("광주광역", "광주"),
    ("대전", "대전"), ("울산", "울산"), ("세종", "세종"), ("경기", "경기"), ("강원", "강원"),
    ("충청북", "충북"), ("충북", "충북"), ("충청남", "충남"), ("충남", "충남"),
    ("전라북", "전북"), ("전북", "전북"), ("전라남", "전남"), ("전남", "전남"),
    ("경상북", "경북"), ("경북", "경북"), ("경상남", "경남"), ("경남", "경남"), ("제주", "제주"),
    ("광주", "광주"),  # '경기 광주시'와 헷갈리지 않게 맨 마지막, 첫 단어에만 적용
]


def sido_of(text: str) -> str:
    """'대전광역시 서구 …', '충청남도', '서울' → 짧은 시도명. 못 찾으면 빈값"""
    t = (text or "").strip()
    if not t:
        return ""
    first = t.split()[0]
    for pre, name in _SIDO_PREFIX:
        if first.startswith(pre):
            return name
    return ""


def city_of(address: str) -> str:
    """주소 두 번째 단어가 시·군·구면 반환 (세종은 시군구 없음)"""
    parts = (address or "").split()
    if len(parts) >= 2 and re.search(r"(시|군|구)$", parts[1]):
        return parts[1]
    return ""


# ── 분야 분류 ───────────────────────────────────────────────
CATEGORIES = ["뮤지컬·연극", "인형극·아동극", "음악·콘서트", "무용·발레", "마술·서커스",
              "전시", "체험·교육", "축제·행사", "기타"]


def category_of(genre: str, title: str, source: str) -> str:
    g, t = genre or "", title or ""
    if any(k in t for k in ("인형극", "그림자극", "동화극", "아동극", "가족극")):
        return "인형극·아동극"
    if any(k in g + t for k in ("마술", "매직", "서커스", "버블쇼", "버블 쇼", "저글링")):
        return "마술·서커스"
    if "뮤지컬" in g or "연극" in g or "뮤지컬" in t:
        return "뮤지컬·연극"
    if any(k in g for k in ("음악", "국악", "클래식", "콘서트")) or "콘서트" in t:
        return "음악·콘서트"
    if "무용" in g or "발레" in t:
        return "무용·발레"
    if "전시" in g or any(k in t for k in ("전시", "展", "특별전", "기획전")):
        return "전시"
    if any(k in g + t for k in ("체험", "교육", "만들기", "클래스", "캠프", "워크숍")):
        return "체험·교육"
    if source in ("tour", "std_festival", "news") or "축제" in g + t or "행사" in g:
        return "축제·행사"
    return "기타"
