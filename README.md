# GDELT + Tavily News Extraction

GDELT DOC API에서 뉴스 목록을 검색하고, 중복 뉴스를 제거한 뒤 Tavily Extract API와 로컬 본문 정제 로직으로 최종 뉴스 본문 JSON을 생성하는 프로젝트입니다.

## 사용 파일

| 파일 | 역할 |
|---|---|
| `test.py` | GDELT DOC API 검색 설정, 요청, 캐시 처리 |
| `tavily_api/tavily_extract.py` | 메인 실행 파일. GDELT 검색, 중복 제거, Tavily 호출, 본문 정제, JSON 저장 |
| `tavily_api/key.txt` | Tavily API 키 파일. Git에 올리지 않습니다 |
| `tavily_api/extracted_articles.json` | 최종 출력 JSON. 실행 시 새로 생성됩니다 |
| `.gdelt_cache/` | GDELT 응답 캐시와 요청 간격 기록 |

## 입력

기본 입력값은 아래와 같습니다.

| 항목 | 기본값 | 설명 |
|---|---|---|
| 검색어 | `semiconductor` | 외부에서 인자로 변경 가능 |
| 언어 | `korean` | GDELT `sourcelang:korean` 필터 |
| 정렬 | `hybridrel` | 연관도 순 |
| 기간 | `1d` | 최근 하루 기사 |
| GDELT 검색 기사 수 | `20` | GDELT에서 가져올 최대 기사 수 |
| Tavily 전달 기사 수 | `10` | 중복 제거 후 Tavily API에 보낼 최대 URL 수 |

검색어를 생략하면 `semiconductor`가 사용됩니다.

```bash
python3 tavily_api/tavily_extract.py
```

검색어를 직접 입력할 수 있습니다. GDELT 검색은 영어 키워드가 더 안정적으로 동작하는 경우가 많으므로, 검색어는 가능하면 영어로 입력하는 것을 권장합니다. 한국어 기사를 찾더라도 언어 필터는 기본적으로 `sourcelang:korean`이 적용됩니다.

```bash
python3 tavily_api/tavily_extract.py "AI semiconductor"
```

추가 옵션도 사용할 수 있습니다.

```bash
python3 tavily_api/tavily_extract.py "AI semiconductor" --source-lang korean --sort hybridrel --maxrecords 20 --timespan 1d --tavily-count 10
```

## GDELT 호출 형식

기본 실행 시 GDELT에는 다음 GET query parameters가 사용됩니다.

```json
{
  "query": "semiconductor sourcelang:korean",
  "mode": "artlist",
  "format": "json",
  "sort": "hybridrel",
  "maxrecords": 20,
  "timespan": "1d"
}
```

## Tavily 호출 형식

GDELT 결과에서 중복 뉴스를 제거한 뒤 상위 10개 URL만 Tavily Extract API로 전달합니다.

```json
{
  "api_key": "<tavily_api/key.txt 값>",
  "urls": [
    "https://example.com/news-1",
    "https://example.com/news-2"
  ],
  "depth": "basic"
}
```

중복 제거 기준은 아래와 같습니다.

- URL의 `www.` / `m.` 차이를 무시합니다.
- `utm_*`, `fbclid`, `gclid` 같은 추적 파라미터를 제거합니다.
- 정규화된 URL이 같으면 중복으로 봅니다.
- 정규화된 제목이 같으면 중복으로 봅니다.

## 출력

최종 결과는 아래 파일에 저장됩니다.

```text
tavily_api/extracted_articles.json
```

출력 JSON 형식은 다음과 같습니다.

```json
{
  "query": "semiconductor sourcelang:korean",
  "total": 10,
  "results": [
    {
      "url": "https://example.com/news-1",
      "title": "기사 제목",
      "source_domain": "example.com",
      "published_at": "20260525T010000Z",
      "language": "Korean",
      "image_url": "https://example.com/image.jpg",
      "raw_content_length": 12345,
      "cleaned_content": "정제된 기사 본문...",
      "cleaned_content_length": 2345
    }
  ],
  "failed_results": []
}
```

`image_url`은 GDELT의 `socialimage` 값을 사용합니다. GDELT에서 이미지 URL을 제공하지 않으면 빈 문자열입니다.

## 실행 구조

전체 실행 순서는 아래와 같습니다.

1. `tavily_api/tavily_extract.py` 실행
2. `test.py`의 설정으로 GDELT DOC API 호출
3. 최근 1일 한국어 기사 20개를 연관도순으로 조회
4. GDELT 결과에서 URL과 제목 기준으로 중복 뉴스 제거
5. 중복 제거 후 상위 10개 URL을 Tavily Extract API에 전달
6. Tavily 응답의 URL별 raw content 길이를 기록
7. 각 기사 URL을 다시 열어 실제 뉴스 본문을 로컬 정제 로직으로 추출
8. 광고, 댓글, 공유 UI, 저작권 문구 등 본문 외 요소 제거
9. DOM 기반 추출이 실패하면 `trafilatura` fallback 사용
10. 최종 JSON을 `tavily_api/extracted_articles.json`에 저장

## 테스트 실행 방법

기본값으로 전체 파이프라인을 테스트합니다.

```bash
python3 tavily_api/tavily_extract.py
```

정상 실행 시 확인할 항목은 아래와 같습니다.

- GDELT에서 `maxrecords=20`, `timespan=1d`, `sort=hybridrel`, `sourcelang:korean`으로 조회되는지 확인
- 중복 제거 후 기사 수가 출력되는지 확인
- Tavily API 요청 URL 수가 최대 10개인지 확인
- `tavily_api/extracted_articles.json` 파일이 생성되는지 확인
- `failed_results`가 비어 있거나 실패 이유가 기록되는지 확인

문법 검사는 다음 명령으로 수행합니다.

```bash
python3 -m py_compile test.py tavily_api/tavily_extract.py
```

도움말은 다음 명령으로 확인합니다.

```bash
python3 test.py --help
python3 tavily_api/tavily_extract.py --help
```

## 본문 일치 검증

최종 JSON의 `cleaned_content`와 URL의 실제 본문이 일치하는지 느슨한 기준으로 검증할 수 있습니다. 공백, 문장부호, 일부 부가 문구 차이는 무시하고 문자/단어 겹침률을 기준으로 판단합니다.

```bash
python3 - <<'PY'
import difflib
import json
import re
from pathlib import Path

from tavily_api.tavily_extract import extract_news_body

path = Path("tavily_api/extracted_articles.json")
data = json.loads(path.read_text(encoding="utf-8"))


def compact(text):
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", (text or "").lower())


def words(text):
    return re.findall(r"[0-9A-Za-z가-힣]+", (text or "").lower())


def shingles(seq, n):
    if len(seq) < n:
        return set(seq) if seq else set()
    return {tuple(seq[i:i + n]) for i in range(len(seq) - n + 1)}


def char_shingles(text, n=7):
    text = compact(text)
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def compare(saved, live):
    saved_chars = char_shingles(saved)
    live_chars = char_shingles(live)
    char_coverage = len(saved_chars & live_chars) / len(saved_chars) if saved_chars else 0.0

    saved_words = shingles(words(saved), 4)
    live_words = shingles(words(live), 4)
    word_coverage = len(saved_words & live_words) / len(saved_words) if saved_words else 0.0

    seq_ratio = difflib.SequenceMatcher(
        None,
        compact(saved)[:10000],
        compact(live)[:10000],
        autojunk=False,
    ).ratio()

    if len(live or "") < 120:
        return "추출 실패"
    if char_coverage >= 0.78 or word_coverage >= 0.78 or seq_ratio >= 0.82:
        return "일치"
    if char_coverage >= 0.55 or word_coverage >= 0.55 or seq_ratio >= 0.62:
        return "대체로 일치"
    if char_coverage >= 0.30 or word_coverage >= 0.30 or seq_ratio >= 0.40:
        return "부분 일치/확인 필요"
    return "불일치 가능성 높음"


summary = {}
for item in data.get("results", []):
    live = extract_news_body(item.get("url", ""), item.get("title", "")) or ""
    status = compare(item.get("cleaned_content", ""), live)
    summary[status] = summary.get(status, 0) + 1
    print(status, "-", item.get("title", ""))

print("요약:", summary)
PY
```

최근 기본값 테스트에서는 `results` 10개 모두 `일치`로 확인되었습니다.

## 주의 사항

- `tavily_api/key.txt`는 API 키 파일이므로 GitHub에 올리면 안 됩니다.
- `.gdelt_cache/`는 로컬 캐시입니다. 실행 결과 재현에는 필요하지 않습니다.
- `tavily_api/extracted_articles.json`은 실행 결과물입니다. 샘플 결과가 필요하면 민감정보 없는 별도 샘플 파일을 만들어 사용하는 것이 좋습니다.
