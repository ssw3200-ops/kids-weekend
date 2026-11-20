"""네이버 블로그 글 초안 생성 (템플릿 기반, 유료 AI 없음)

- 본문은 통째로 복사·붙여넣기 하도록 [인용구] 같은 표시 없이 생성
- 소제목·인용구는 이미지로 따로 만들고, 넣을 자리는 파일명으로 안내
- 구분선은 글자로 자동 삽입
"""
from __future__ import annotations

import random
from datetime import date

from common import Event

WD = "월화수목금토일"

DIVIDERS = [
    "⋆｡˚ ☁︎ ˚｡⋆｡˚☀︎˚｡⋆｡˚ ☁︎ ˚｡⋆",
    "･ﾟ✧ ･ﾟ✧ ･ﾟ✧ ･ﾟ✧ ･ﾟ✧ ･ﾟ✧",
    "♡ ━━━━━━ ♡ ━━━━━━ ♡",
    "✿ ･ ･ ･ ･ ✿ ･ ･ ･ ･ ✿ ･ ･ ･ ･ ✿",
    "☆ ･ ･ ･ ･ ☆ ･ ･ ･ ･ ☆ ･ ･ ･ ･ ☆",
]

INTROS = [
    "안녕하세요, 세 아이 아빠예요 😊\n주말만 되면 \"아빠 오늘 어디 가?\" 소리에 머리가 하얘지시죠?\n그래서 이번 주말 {regions}에서 아이랑 갈 만한 행사들을 싹 모아봤어요!",
    "이번 주말은 또 뭐 하고 놀지… 고민되는 엄마 아빠들 모여라~ 🙌\n{regions} 지역 아이랑 가볼 만한 체험·전시·행사를 한 번에 정리했어요.",
    "주말 계획 아직 못 세우셨다면 딱 이 글 하나면 돼요!\n쌍둥이 포함 세 아이 데리고 다니는 아빠 눈으로 {regions} 주말 행사만 골라봤어요 🎈",
]

OUTROS = [
    "이번 주말도 아이들이랑 웃음 가득한 시간 보내세요 💛\n다녀오신 곳 후기도 댓글로 알려주시면 다음 글에 반영할게요!",
    "주말 나들이 고민 조금은 덜어졌으면 좋겠어요 🥰\n매주 목요일마다 새로 정리해서 올리니까 이웃추가 해두시면 편해요!",
    "아이들이 \"또 가자!\" 하는 주말 되시길 바라요 🌈\n궁금한 행사 있으면 댓글 남겨주세요. 아는 데까지 알려드릴게요!",
]

TIPS = [
    "인기 아동 공연은 주말 직전에 매진되는 경우가 많아요. 예매부터 하고 일정 짜기!",
    "야외 행사는 날씨 따라 바뀔 수 있어요. 출발 전에 공식 공지 꼭 한 번 확인하세요!",
    "주차가 제일 큰 복병이에요. 근처 공영주차장 위치를 미리 봐 두면 마음이 편해요.",
    "다자녀·지역주민 할인이 있는 곳이 많아요. 다자녀 카드랑 신분증 꼭 챙기세요!",
    "간식이랑 여벌 옷 하나만 챙겨도 반나절이 평화로워요. 아빠의 생존 꿀팁!",
]

GENRE_EMOJI = {"뮤지컬": "🎤", "연극": "🎭", "아동": "🧸", "전시": "🖼️", "축제": "🎉",
               "행사": "🎈", "서양음악": "🎻", "클래식": "🎻", "무용": "🩰", "복합": "✨"}


# 글 안 묶음: (이름, 이모지, 판별 함수) — 위에서부터 먼저 맞는 것
SEASON_WORDS = ("크리스마스", "산타", "트리", "점등", "눈썰매", "겨울", "빛축제", "빛 축제", "루미나", "연말", "새해", "해맞이")
SHOW_CATS = ("뮤지컬·연극", "인형극·아동극", "음악·콘서트", "무용·발레", "마술·서커스")


def _txt(ev: Event) -> str:
    return f"{ev.title} {ev.genre} {ev.place}"


KINDS = [
    ("시즌 행사", "🎄", lambda e: any(w in e.title for w in SEASON_WORDS)),
    ("과학관", "🔬", lambda e: "과학관" in _txt(e) or "과학" in e.genre),
    ("도서관", "📚", lambda e: "도서관" in _txt(e)),
    ("박물관", "🏛️", lambda e: "박물관" in _txt(e) and e.category != "전시"),
    ("체험", "🎨", lambda e: e.category == "체험·교육" or e.source == "org" and "체험" in e.genre),
    ("전시", "🖼️", lambda e: e.category == "전시"),
    ("축제·행사", "🎉", lambda e: e.category in ("축제·행사", "기타") and e.category not in SHOW_CATS),
    ("공연", "🎤", lambda e: True),
]


def kind_of(ev: Event) -> tuple[str, str]:
    for name, emo, fn in KINDS:
        if fn(ev):
            return name, emo
    return "공연", "🎤"


def is_show(ev: Event) -> bool:
    return kind_of(ev)[0] == "공연"


def kdate(d: date) -> str:
    return f"{d.month}월 {d.day}일({WD[d.weekday()]})"


def period_text(ev: Event) -> str:
    if ev.start == ev.end:
        return kdate(ev.start)
    if (ev.end - ev.start).days > 14:
        return f"{kdate(ev.end)}까지 진행 중"
    return f"{kdate(ev.start)} ~ {kdate(ev.end)}"


def emoji_for(ev: Event) -> str:
    for k, v in GENRE_EMOJI.items():
        if k in ev.genre or k in ev.title:
            return v
    return "🎈"


def event_block(i: int, ev: Event) -> str:
    kind, emo = kind_of(ev)
    lines = [f"{i}. {emo if kind != '공연' else emoji_for(ev)} {ev.title}"]
    lines.append(f"📅 {period_text(ev)}")
    if ev.place or ev.address:
        lines.append(f"📍 {ev.place or ev.address}")
    lines.append(f"💰 {ev.price if ev.price else '요금은 상세페이지에서 확인'}")
    if ev.age:
        lines.append(f"👶 추천 연령: {ev.age}")
    days = next((t for t in ev.tags if t.startswith("운영요일")), "")
    if days:
        lines.append(f"🗓️ {days} (날짜 안에서 이 요일만)")
    if ev.source == "org" and any(t in ("접수중", "접수대기") or "신청" in t or "예약" in t or "접수" in t for t in ev.tags):
        lines.append("📝 사전 예약 필요 — 링크에서 신청")
    point = [t for t in ev.tags if t not in ("무료", "접수중", "접수대기", "기사") and not t.startswith("운영요일")
             and "신청" not in t and "접수" not in t
             and t not in (ev.place,)]
    point = [t for t in point if len(t) <= 12]
    if ev.is_free:
        point.insert(0, "무료라서 부담 없음")
    if point:
        lines.append(f"✔️ {' · '.join(point[:3])}")
    if ev.link:
        lines.append(f"🔗 {ev.link}")
    return "\n".join(lines)


def build(events: list[Event], regions: list[str], wk_start: date, wk_end: date,
          seed: str, page_url: str = "") -> dict:
    rnd = random.Random(seed)
    div = rnd.choice(DIVIDERS)
    reg_txt = "·".join(regions)
    span = f"{wk_start.month}/{wk_start.day}~{wk_end.month}/{wk_end.day}"

    titles = [
        f"{reg_txt} 아이랑 갈만한곳 이번 주말 행사 총정리 ({span})",
        f"이번 주말 {reg_txt} 아이랑 가볼만한 체험·전시·축제 ({span})",
        f"{reg_txt} 주말 무료 체험부터 시즌 행사까지 아이랑 갈만한곳 ({span})",
        f"{span} {reg_txt} 주말 아이랑 놀거리 BEST {len(events)}",
    ]

    images: list[tuple[str, str]] = [("01_표지.png", "글 맨 위 (대표 이미지)")]
    parts: list[str] = [rnd.choice(INTROS).format(regions=reg_txt)]
    parts.append(f"📆 기간: {kdate(wk_start)} ~ {kdate(wk_end)}")
    free_cnt = sum(1 for e in events if e.is_free)
    if free_cnt:
        parts.append(f"💡 이번 주는 무료 행사도 {free_cnt}개나 있어요!")
    parts.append(div)

    n = 1
    img_no = 2
    for reg in regions:
        evs = [e for e in events if e.region == reg]
        if not evs:
            continue
        images.append((f"{img_no:02d}_{reg}편.png", f"'{reg} 아이랑 행사' 목록 바로 위"))
        img_no += 1
        parts.append(f"{reg} 아이랑 행사 🎈")
        order = [k[0] for k in KINDS]
        evs.sort(key=lambda e: order.index(kind_of(e)[0]))
        last = ""
        for ev in evs:
            kind, emo = kind_of(ev)
            if kind != last:
                parts.append(f"{emo} {kind}")
                last = kind
            parts.append(event_block(n, ev))
            n += 1
        parts.append(div)

    tip = rnd.choice(TIPS)
    images.append((f"{img_no:02d}_아빠꿀팁.png", "마지막 구분선 바로 아래 (마무리 인사 위)"))
    if page_url:
        parts.append("📌 개발자 아빠가 직접 만든 \"전국 아이랑 행사 모아보기\" 페이지도 있어요!\n"
                     "지역·분야·무료만 골라 볼 수 있고 매주 자동으로 업데이트돼요.\n"
                     "댓글 남겨주시면 비밀댓글로 링크랑 비밀번호 보내드릴게요 💌")
    parts.append(rnd.choice(OUTROS))
    tags = ["#" + reg + t for reg in regions for t in ("아이랑갈만한곳", "주말행사", "가볼만한곳")]
    tags += ["#아이랑주말", "#주말나들이", "#아이랑오늘뭐하지", "#아이랑체험", "#무료체험", "#가족나들이"]
    parts.append(" ".join(tags))

    return {
        "titles": titles,
        "body": "\n\n".join(parts),
        "images": images,
        "tip": tip,
        "cover_lines": (f"{' & '.join(regions)} 주말", "아이랑 어디 갈까?"),
        "badge": f"{kdate(wk_start)} ~ {kdate(wk_end)}",
    }
