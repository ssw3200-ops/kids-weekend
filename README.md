# 이번 주말 아이랑 어디 갈까? (kids-weekend)

세종·대전 주말 아이랑 행사를 **매주 목요일 밤 자동으로** 모아서

1. 휴대폰용 공개 페이지(`docs/index.html`)를 갱신하고
2. 네이버 블로그 글 초안(본문 + 제목 후보 + 표지·소제목·꿀팁 이미지 ZIP)을 만듭니다.

전부 무료예요 (GitHub Actions·Pages 무료, 공공데이터 API 무료).

## 데이터 소스

| 소스 | 내용 | 키 |
|---|---|---|
| 한국관광공사 국문 관광정보 서비스_GW (`searchFestival2`) | 지역 축제·행사 | 공공데이터포털 키 |
| 한국문화정보원 한눈에보는문화정보 (`period2`) | 공연·전시 | 공공데이터포털 키 (같은 키) |
| KOPIS 공연예술통합전산망 (`pblprfr`, 아동공연만) | 아동 공연·뮤지컬 | KOPIS 키 |
| `manual_events.yaml` | API에 없는 행사 직접 추가 | 없음 |

> 문화정보원 API는 활용신청 후 '활용명세'에서 오퍼레이션 경로와 필드명을 한 번 확인하세요. 다르면 `src/collect_culture.py` 위쪽 `URL`/`FIELD`만 고치면 됩니다.

## 휴대폰으로 설정하기 (한 번만)

1. GitHub에서 새 저장소 `kids-weekend` 만들기 (**Public**이어야 Actions·Pages 무료)
2. 이 폴더 파일 전부 업로드 (ZIP 압축 풀어서 `Add file → Upload files`)
   - `.github` 폴더는 숨김 폴더라 휴대폰 업로드 때 빠지기 쉬워요. 빠졌으면 `Add file → Create new file`에서 이름을 `.github/workflows/weekly.yml`로 하고 내용을 붙여넣으세요.
3. `Settings → Secrets and variables → Actions → New repository secret`
   - `DATA_GO_KR_KEY` : 공공데이터포털 **일반 인증키(Decoding)**
   - `KOPIS_KEY` : KOPIS 서비스키
4. `Settings → Pages` → Source: **Deploy from a branch**, Branch: `main` / 폴더: `/docs` → Save
5. `Actions` 탭 → "주말 행사 자동 수집" → **Run workflow** (처음 한 번 수동 실행)

## 매주 쓰는 법

- 공개 페이지: `https://ssw3200-ops.github.io/kids-weekend/` → 블로그 글 끝에 링크
- 초안 페이지: `https://ssw3200-ops.github.io/kids-weekend/draft.html`
  1. 제목 후보 중 하나 복사
  2. "본문 전체 복사" → 네이버 블로그에 통째로 붙여넣기
  3. "이미지 ZIP 받기" → 파일명에 적힌 위치에 사진 넣기
- 본문 말투를 더 사람답게 다듬고 싶으면 본문을 Claude에 붙여넣고 "블로그 톤으로 다듬어줘" 하면 돼요.

## 설정 바꾸기

- 지역 추가: `config.yaml`의 `regions`에 한 줄 추가 (서울이면 tour_ldong `11`, kopis `11`, culture `서울`)
- 아이 행사 판별 키워드: `config.yaml`의 `keywords`
- 실행 시간: `.github/workflows/weekly.yml`의 `cron` (UTC 기준, 지금은 목요일 21:07 KST)

## 로컬 테스트

```bash
pip install -r requirements.txt
python src/build.py --sample                       # 키 없이 샘플로
DATA_GO_KR_KEY=... KOPIS_KEY=... python src/build.py
```

폰트: Jua (SIL Open Font License, `fonts/OFL.txt`)
