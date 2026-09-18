# GDELT News Extraction

GDELT DOC API에서 뉴스 목록을 검색하고, 중복 뉴스를 제거한 뒤 Tavily Extract API, Diffbot Article API, Jina Reader API로 뉴스 본문 JSON을 생성하는 프로젝트입니다.

## 사용 파일

| 파일 | 역할 |
|---|---|
| `test.py` | GDELT DOC API 검색 설정, 요청, 캐시 처리 |
| `tavily_api/tavily_extract.py` | 메인 실행 파일. GDELT 검색, 중복 제거, Tavily 호출, 본문 정제, JSON 저장 |
| `tavily_api/key.txt` | Tavily API 키 파일. Git에 올리지 않습니다 |
| `tavily_api/extracted_articles.json` | 최종 출력 JSON. 실행 시 새로 생성됩니다 |
| `diffbot/diffbot_extract.py` | Diffbot Article API로 뉴스 본문을 추출하는 실행 파일 |
| `diffbot/diffbot_extract_md.py` | Diffbot Article API 결과를 Markdown으로 저장하는 실행 파일 |
| `jina_reader/jina_reader_extract.py` | Jina Reader API로 뉴스 본문을 추출하는 실행 파일 |
| `currents_news_api/currents_news_extract.py` | Currents News API로 `test.py`의 입력값을 적용해 뉴스 목록 JSON 생성 |
| `BODY_MATCH_VALIDATION.md` | 저장된 기사 본문과 실제 URL 본문이 일치하는지 검증하는 방법 |
| `diffbot/token.txt` | Diffbot API token 파일. Git에 올리지 않습니다 |
| `diffbot/extracted_articles.json` | Diffbot 추출 결과 JSON. 실행 시 새로 생성됩니다 |
| `diffbot/extracted_articles.md` | Diffbot Markdown 추출 결과. 실행 시 새로 생성됩니다 |
| `jina_reader/key.txt` | Jina API key 파일. 선택 사항이며 Git에 올리지 않습니다 |
| `jina_reader/extracted_articles.json` | Jina Reader 추출 결과 JSON. 실행 시 새로 생성됩니다 |
| `currents_news_api/key.env` | Currents API key 파일. Git에 올리지 않습니다 |
| `currents_news_api/extracted_articles.json` | Currents 검색 결과 JSON. 실행 시 새로 생성됩니다 |
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
| Diffbot 전달 기사 수 | `10` | 중복 제거 후 Diffbot Article API에 보낼 최대 URL 수 |
| Jina Reader 전달 기사 수 | `10` | 중복 제거 후 Jina Reader API에 보낼 최대 URL 수 |

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

## Diffbot로 기사 본문 추출

Diffbot token은 아래 파일에 저장합니다. 이 파일은 Git에 올리지 않습니다.

```text
diffbot/token.txt
```

GDELT에서 기사 URL을 검색한 뒤 중복 제거된 상위 URL을 Diffbot Article API에 전달합니다.

```bash
python3 diffbot/diffbot_extract.py
python3 diffbot/diffbot_extract.py "AI semiconductor" --diffbot-count 5
```

특정 기사 URL만 바로 추출할 수도 있습니다.

```bash
python3 diffbot/diffbot_extract.py --url "https://example.com/news/article"
```

URL 목록 파일을 사용할 수도 있습니다. 파일은 한 줄에 하나의 URL을 넣습니다.

```bash
python3 diffbot/diffbot_extract.py --url-file urls.txt --diffbot-count 10
```

Diffbot 출력은 기본적으로 아래 파일에 저장됩니다.

```text
diffbot/extracted_articles.json
```

JSON 없이 Markdown 파일만 만들려면 별도 Markdown 전용 스크립트를 사용합니다.

```bash
python3 diffbot/diffbot_extract_md.py
python3 diffbot/diffbot_extract_md.py "AI semiconductor" --diffbot-count 5
python3 diffbot/diffbot_extract_md.py --url "https://example.com/news/article"
```

Markdown 출력은 기본적으로 아래 파일에 저장됩니다.

```text
diffbot/extracted_articles.md
```

본문이 동적으로 늦게 로드되는 기사에는 Diffbot 렌더링 옵션을 추가할 수 있습니다.

```bash
python3 diffbot/diffbot_extract.py "AI semiconductor" --render-delay-ms 3000 --scroll slow
```

Diffbot API 응답의 `text` 필드를 본문으로 저장합니다. Diffbot `text`가 비어 있을 때 기존 로컬 DOM/trafilatura 추출 로직까지 시도하려면 `--fallback-local`을 추가합니다.

## Jina Reader로 기사 본문 추출

Jina Reader API는 키 없이도 호출할 수 있습니다. 더 높은 rate limit을 쓰려면 아래 파일에 Jina API key를 저장합니다.

```text
jina_reader/key.txt
```

GDELT에서 기사 URL을 검색한 뒤 중복 제거된 상위 URL을 Jina Reader API에 전달합니다.

```bash
python3 jina_reader/jina_reader_extract.py
python3 jina_reader/jina_reader_extract.py "AI semiconductor" --jina-count 5
```

특정 기사 URL만 바로 추출할 수도 있습니다.

```bash
python3 jina_reader/jina_reader_extract.py --url "https://example.com/news/article"
```

URL 목록 파일을 사용할 수도 있습니다. 파일은 한 줄에 하나의 URL을 넣습니다.

```bash
python3 jina_reader/jina_reader_extract.py --url-file urls.txt --jina-count 10
```

Jina Reader 출력은 Diffbot JSON과 같은 top-level 구조로 아래 파일에 저장됩니다.

```text
jina_reader/extracted_articles.json
```

Jina Reader 요청은 뉴스 본문 추출 정확도를 높이기 위해 기본적으로 브라우저 렌더링과 캐시 우회를 사용합니다.

```http
X-Engine: browser
X-Respond-Timing: network-idle
X-Timeout: 45
X-Retain-Images: none
X-Retain-Links: text
X-Detach-Invisibles: true
X-No-Cache: true
```

동적 본문 로딩이 늦은 기사에는 Reader 옵션을 추가로 조정할 수 있습니다.

```bash
python3 jina_reader/jina_reader_extract.py "AI semiconductor" --respond-timing resource-idle --timeout 60
python3 jina_reader/jina_reader_extract.py --url "https://example.com/news/article" --wait-for-selector article
```

Jina Reader 요청에는 기본적으로 `X-Target-Selector`와 `X-Remove-Selector`를 함께 적용합니다. 기본 target selector는 `article`, `main`, `#articleBody`, `.article-body`, `.news_body` 같은 본문 컨테이너 후보이고, 기본 remove selector는 `nav`, `header`, `footer`, 광고, 댓글, 관련기사, 공유 UI 후보입니다. 사이트별로 더 정확한 selector를 알고 있으면 아래처럼 덮어쓸 수 있습니다.

```bash
python3 jina_reader/jina_reader_extract.py --url "https://example.com/news/article" --target-selector "article" --remove-selector "nav, header, footer, .ad, .related"
```

Jina Reader JSON 응답의 `content` 필드를 본문으로 사용하고, Markdown 이미지/링크/제목 중복을 제거한 plain text를 `cleaned_content`에 저장합니다.

## Currents News API로 뉴스 목록 검색

Currents API key는 아래 파일에 저장합니다. 이 파일은 Git에 올리지 않습니다.

```text
currents_news_api/key.env
```

예시는 아래와 같습니다.

```text
CURRENTS_API_KEY=YOUR_API_KEY
```

`test.py`의 기본 입력값을 Currents Search API 파라미터로 변환합니다. 기본 검색어 `semiconductor`는 `keywords`, 기본 언어 `korean`은 Currents 언어 코드 `ko`, 기본 기사 수 `20`은 `page_size`, 기본 기간 `1d`는 `start_date`로 적용됩니다.

```bash
python3 currents_news_api/currents_news_extract.py
python3 currents_news_api/currents_news_extract.py "AI 반도체" --maxrecords 5
python3 currents_news_api/currents_news_extract.py "AI 반도체" --source-lang korean --timespan 1d --country KR
```

Currents 출력은 아래 파일에 저장됩니다.

```text
currents_news_api/extracted_articles.json
```

Currents Search API 결과는 GDELT에서 수집한 기사 목록과 같은 메타데이터 필드로 저장합니다. 기사 본문은 Currents에서 저장하지 않고, 이후 Diffbot 같은 본문 추출 API가 URL을 받아 추출합니다.

## GDELT 사용 주의사항

GDELT DOC API는 RPM(requests per minute) 제한이 강하게 걸릴 수 있습니다. 이 프로젝트의 `test.py`는 로컬 실행 중 과도한 반복 요청을 줄이기 위해 요청 간격과 캐시를 사용하지만, 실제 배포 환경에서는 기본 테스트 간격보다 훨씬 긴 호출 간격을 두어야 합니다.

자동 배치, 서버 API, 사용자 요청에 따른 실시간 검색처럼 반복 호출이 발생할 수 있는 환경에서는 GDELT를 짧은 주기로 직접 호출하지 않는 것을 권장합니다. 운영 환경에서는 요청 수를 제한하고, 검색 결과 캐시를 적극적으로 사용하며, 같은 검색어에 대한 재조회 간격을 충분히 길게 잡아야 합니다.

개발 중 반복 테스트나 빠른 응답 확인이 목적이라면 GDELT보다 별도 API를 사용하는 편이 좋습니다. 예를 들어 Currents News API는 테스트용 뉴스 목록 확인에 사용할 수 있고, Diffbot/Jina Reader는 이미 확보한 URL의 본문 추출 흐름을 검증하는 용도로 사용할 수 있습니다.

## 뉴스 검색 API 변경 방법

뉴스 검색 API는 기사 URL과 메타데이터를 수집하는 단계입니다. Diffbot, Jina Reader, Tavily는 이 URL을 받아 본문을 추출하는 단계이므로, 검색 API를 바꿀 때는 본문 필드가 아니라 기사 목록 메타데이터 형식을 맞추는 것이 중요합니다.

새 검색 API를 추가하거나 GDELT 대신 다른 API를 사용하려면 결과를 아래 `results` 항목 형태로 정규화합니다.

```json
{
  "title": "기사 제목",
  "url": "https://example.com/news-1",
  "source_domain": "example.com",
  "published_at": "2026-05-25 01:00:00 +0000",
  "language": "ko",
  "image_url": "https://example.com/image.jpg"
}
```

필수 필드는 `url`입니다. `title`, `source_domain`, `published_at`, `language`, `image_url`은 가능한 경우 채우고, API가 제공하지 않으면 빈 문자열로 둡니다. 검색 API 출력에는 `cleaned_content`나 `cleaned_content_length`를 넣지 않습니다. 본문은 이후 Diffbot 같은 본문 추출 API가 채웁니다.

검색 API 스크립트의 최종 JSON은 아래 top-level 구조를 유지합니다.

```json
{
  "query": "semiconductor sourcelang:korean",
  "total": 10,
  "results": [],
  "failed_results": []
}
```

API별 변경 절차는 아래 순서를 따릅니다.

1. 새 API용 디렉터리와 실행 파일을 만듭니다. 예: `currents_news_api/currents_news_extract.py`
2. API key 파일과 실행 결과 JSON이 Git에 올라가지 않도록 `.gitignore`에 추가합니다.
3. 새 API 응답을 공통 기사 메타데이터 필드로 변환하는 정규화 함수를 만듭니다.
4. URL과 제목 기준 중복 제거 로직을 적용합니다.
5. 최종 JSON을 `query`, `total`, `results`, `failed_results` 구조로 저장합니다.
6. Diffbot 같은 본문 추출기는 `results[*].url`을 입력으로 사용하고, 기존 메타데이터에 본문 추출 결과를 합쳐 저장합니다.
7. README의 사용 파일, 실행 예시, 테스트 명령을 새 API에 맞게 갱신합니다.

기존 GDELT 검색을 코드에서 직접 교체하려면 각 추출기의 `collect_urls_from_gdelt()` 역할을 하는 함수가 반환하는 리스트를 위 메타데이터 형식으로 맞추면 됩니다. 이렇게 하면 검색 API가 GDELT인지 Currents인지와 관계없이 이후 본문 추출 단계는 같은 입력 형식을 사용할 수 있습니다.

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

각 추출기는 실행 결과를 자기 디렉터리의 결과 파일에 저장합니다.

| 추출기 | 기본 출력 파일 | 설명 |
|---|---|---|
| Tavily | `tavily_api/extracted_articles.json` | Tavily raw content 길이와 로컬 정제 본문 저장 |
| Diffbot | `diffbot/extracted_articles.json` | Diffbot `text` 길이와 정제 본문 저장 |
| Diffbot Markdown | `diffbot/extracted_articles.md` | Diffbot 결과를 사람이 읽기 쉬운 Markdown으로 저장 |
| Jina Reader | `jina_reader/extracted_articles.json` | Jina Reader `content` 길이와 정제 본문 저장 |
| Currents | `currents_news_api/extracted_articles.json` | GDELT 기사 목록과 같은 메타데이터 필드 저장 |

JSON 출력은 추출기와 관계없이 같은 top-level 구조를 사용합니다.

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
      "cleaned_content": "정제된 기사 본문...",
      "cleaned_content_length": 2345
    }
  ],
  "failed_results": []
}
```

`query`에는 실제 GDELT query 문자열이 들어갑니다. `--url` 또는 `--url-file`로 직접 URL을 입력한 Diffbot/Jina 실행에서는 `direct-url`이 들어갑니다. `total`은 성공적으로 저장된 기사 수이고, `failed_results`에는 실패한 URL과 오류 메시지가 들어갑니다.

Currents 결과의 `results` 항목은 Diffbot 입력으로 바로 넘길 수 있도록 GDELT 기사 목록과 같은 메타데이터 필드만 사용합니다.

```json
{
  "url": "https://example.com/news-1",
  "title": "기사 제목",
  "source_domain": "example.com",
  "published_at": "2026-05-25 01:00:00 +0000",
  "language": "ko",
  "image_url": "https://example.com/image.jpg"
}
```

Tavily 결과의 `results` 항목은 아래 필드를 사용합니다.

```json
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
```

Diffbot 결과의 `results` 항목은 Diffbot Article API의 `text` 필드 길이를 함께 저장합니다.

```json
{
  "url": "https://example.com/news-1",
  "title": "기사 제목",
  "source_domain": "example.com",
  "published_at": "20260525T010000Z",
  "language": "Korean",
  "image_url": "https://example.com/image.jpg",
  "diffbot_text_length": 2345,
  "cleaned_content": "정제된 기사 본문...",
  "cleaned_content_length": 2345
}
```

Jina Reader 결과의 `results` 항목은 Reader 응답 제목과 원본 content 길이를 함께 저장합니다.

```json
{
  "url": "https://example.com/news-1",
  "title": "기사 제목",
  "source_domain": "example.com",
  "published_at": "20260525T010000Z",
  "language": "Korean",
  "image_url": "https://example.com/image.jpg",
  "jina_title": "Reader 응답 제목",
  "jina_content_length": 3456,
  "cleaned_content": "정제된 기사 본문...",
  "cleaned_content_length": 2345
}
```

`image_url`은 GDELT의 `socialimage` 값을 사용합니다. GDELT에서 이미지 URL을 제공하지 않거나 직접 URL을 입력하면 빈 문자열입니다.

## 실행 구조

세 추출기는 GDELT 기사 URL 수집과 중복 제거 로직을 공유합니다.

1. 실행 스크립트에서 검색어와 옵션을 읽습니다.
2. `test.py`의 `build_gdelt_params()`로 GDELT DOC API query parameters를 만듭니다.
3. `fetch_gdelt_json()`으로 최근 1일 한국어 기사 목록을 가져옵니다.
4. GDELT 결과를 `title`, `url`, `source_domain`, `published_at`, `language`, `image_url` 메타데이터로 변환합니다.
5. URL의 `www.` / `m.` 차이와 추적 파라미터를 정규화하고, URL 또는 제목이 같은 기사를 제거합니다.
6. 각 추출기의 count 옵션만큼 상위 URL을 잘라 본문 추출 API에 전달합니다.

Tavily 실행 순서는 아래와 같습니다.

1. `tavily_api/tavily_extract.py` 실행
2. 중복 제거 후 상위 URL을 Tavily `/extract` API에 `depth=basic`으로 전달
3. Tavily 응답의 URL별 `raw_content` 길이를 `raw_content_length`에 기록
4. 각 기사 URL을 다시 열어 로컬 DOM 기반 본문 정제 로직 실행
5. 광고, 댓글, 공유 UI, 저작권 문구 등 본문 외 요소 제거
6. DOM 기반 추출이 실패하면 `trafilatura` fallback 사용
7. 최종 JSON을 `tavily_api/extracted_articles.json`에 저장

Diffbot 실행 순서는 아래와 같습니다.

1. `diffbot/diffbot_extract.py` 실행
2. `diffbot/token.txt` 또는 `--token-file`에서 Diffbot token 로드
3. GDELT에서 수집한 URL 또는 `--url`, `--url-file`로 직접 입력한 URL 준비
4. 각 URL을 Diffbot Article API `/v3/article`에 GET 요청으로 전달
5. 필요하면 `--render-delay-ms`, `--scroll`, `--use-proxy`, `--natural-language` 옵션을 함께 전달
6. 응답 `objects[0].text`를 문단 단위로 정규화해 `cleaned_content`에 저장
7. Diffbot `text`가 비었고 `--fallback-local`이 있으면 Tavily의 로컬 DOM/trafilatura 추출기를 한 번 더 실행
8. 최종 JSON을 `diffbot/extracted_articles.json` 또는 `--output` 경로에 저장

`diffbot/diffbot_extract_md.py`는 같은 Diffbot 추출 과정을 사용하지만 JSON 대신 Markdown 문서를 만듭니다. 각 기사에는 URL, source, published time, language, image, 본문 길이, 본문이 순서대로 기록됩니다.

Jina Reader 실행 순서는 아래와 같습니다.

1. `jina_reader/jina_reader_extract.py` 실행
2. `jina_reader/key.txt` 또는 `--api-key-file`이 있으면 Jina API key 로드. 없으면 키 없이 호출
3. GDELT에서 수집한 URL 또는 `--url`, `--url-file`로 직접 입력한 URL 준비
4. 각 URL을 Jina Reader `https://r.jina.ai/`에 POST 요청으로 전달
5. 기본 헤더로 `X-Engine: browser`, `X-Respond-Timing: network-idle`, `X-No-Cache: true`, target/remove selector를 적용
6. 응답 `data.content` 또는 `data.text`에서 Markdown 이미지, 링크 URL, 제목 중복, boilerplate 문구 제거
7. 정제된 plain text를 `cleaned_content`에 저장
8. 최종 JSON을 `jina_reader/extracted_articles.json` 또는 `--output` 경로에 저장

## 테스트 실행 방법

먼저 문법 검사를 수행합니다.

```bash
python3 -m py_compile test.py tavily_api/tavily_extract.py diffbot/diffbot_extract.py diffbot/diffbot_extract_md.py jina_reader/jina_reader_extract.py currents_news_api/currents_news_extract.py
```

도움말은 다음 명령으로 확인합니다.

```bash
python3 test.py --help
python3 tavily_api/tavily_extract.py --help
python3 diffbot/diffbot_extract.py --help
python3 diffbot/diffbot_extract_md.py --help
python3 jina_reader/jina_reader_extract.py --help
python3 currents_news_api/currents_news_extract.py --help
```

GDELT 검색과 Tavily 전체 파이프라인은 기본값으로 테스트합니다. `tavily_api/key.txt`가 필요하고, 기본 출력 파일을 덮어씁니다.

```bash
python3 tavily_api/tavily_extract.py
```

Diffbot JSON 출력은 API 사용량을 줄이기 위해 직접 URL 1개로 테스트하는 것을 권장합니다. `diffbot/token.txt`가 필요합니다.

```bash
python3 diffbot/diffbot_extract.py --url "https://example.com/news/article" --output /tmp/diffbot_test.json --request-interval 0
```

Diffbot Markdown 출력도 같은 방식으로 테스트할 수 있습니다.

```bash
python3 diffbot/diffbot_extract_md.py --url "https://example.com/news/article" --output /tmp/diffbot_test.md --request-interval 0
```

Jina Reader는 키 없이도 직접 URL 1개로 테스트할 수 있습니다. API key가 반드시 필요한 환경에서는 `--require-api-key`를 추가합니다.

```bash
python3 jina_reader/jina_reader_extract.py --url "https://example.com/news/article" --output /tmp/jina_test.json --request-interval 0
python3 jina_reader/jina_reader_extract.py --url "https://example.com/news/article" --require-api-key --output /tmp/jina_test.json --request-interval 0
```

GDELT 검색까지 포함한 Diffbot/Jina 테스트는 count를 1로 낮춰 실행합니다.

```bash
python3 diffbot/diffbot_extract.py "AI semiconductor" --diffbot-count 1 --output /tmp/diffbot_gdelt_test.json --request-interval 0
python3 jina_reader/jina_reader_extract.py "AI semiconductor" --jina-count 1 --output /tmp/jina_gdelt_test.json --request-interval 0
```

정상 실행 시 확인할 항목은 아래와 같습니다.

- GDELT 실행에서는 `maxrecords=20`, `timespan=1d`, `sort=hybridrel`, `sourcelang:korean`으로 조회되는지 확인
- 중복 제거 후 기사 수와 각 URL이 출력되는지 확인
- API 요청 URL 수가 `--tavily-count`, `--diffbot-count`, `--jina-count` 값을 넘지 않는지 확인
- 지정한 JSON 또는 Markdown 출력 파일이 생성되는지 확인
- `results`에는 본문과 길이 필드가 기록되고, 실패한 URL은 `failed_results`에 오류 이유가 기록되는지 확인

## 본문 일치 검증

저장된 `cleaned_content`와 URL의 실제 본문이 일치하는지 확인하는 방법은 [BODY_MATCH_VALIDATION.md](BODY_MATCH_VALIDATION.md)를 참고합니다.

## 품질 검증 결론

Tavily, Diffbot, Jina Reader 결과를 같은 기사 raw 본문과 비교한 품질 검증에서는 본문 순도 기준으로 `Diffbot ≈ Tavily > Jina`로 판단했습니다. Jina Reader는 평균 본문 길이와 raw 커버리지가 가장 높지만, 공유 UI, 관련기사, 광고/영상 블록 같은 본문 외 요소가 더 많이 섞이는 경향이 있습니다.

요약 지표는 아래와 같습니다. raw 자체가 한글 깨짐이었던 `#2 국민일보`는 품질 판단용 요약에서 제외했고, Jina 10번은 `HTTP 451` 차단으로 갱신 결과가 실패해 이전 성공 결과로 대체해 계산했습니다.

| 도구 | 평균 본문 길이 | raw 대비 길이 | 정합도 | raw 커버리지 | 잡음 합계 |
|---|---:|---:|---:|---:|---:|
| Tavily | 2,347자 | 24.4% | 99.2% | 36.1% | 1 |
| Diffbot | 2,281자 | 23.5% | 99.5% | 35.0% | 2 |
| Jina Reader | 2,894자 | 27.2% | 98.1% | 40.9% | 12 |

용도별 판단은 아래와 같습니다.

- 깨끗한 본문 JSON이 목적이면 `Diffbot` 또는 `Tavily`를 우선 사용합니다.
- 본문을 더 많이 회수하는 것이 목적이면 `Jina Reader`가 유리합니다.
- Jina Reader를 사용할 때는 공유 UI, 관련기사, 광고/영상 블록 제거 후처리를 반드시 적용하는 것이 좋습니다.

## 주의 사항

- `tavily_api/key.txt`는 API 키 파일이므로 GitHub에 올리면 안 됩니다.
- `diffbot/token.txt`는 API token 파일이므로 GitHub에 올리면 안 됩니다.
- `jina_reader/key.txt`는 선택 사항이지만 API key 파일이므로 GitHub에 올리면 안 됩니다.
- `.gdelt_cache/`는 로컬 캐시입니다. 실행 결과 재현에는 필요하지 않습니다.
- `tavily_api/extracted_articles.json`은 실행 결과물입니다. 샘플 결과가 필요하면 민감정보 없는 별도 샘플 파일을 만들어 사용하는 것이 좋습니다.
- `diffbot/extracted_articles.json`은 Diffbot 실행 결과물입니다.
- `diffbot/extracted_articles.md`는 Diffbot Markdown 실행 결과물입니다.
- `jina_reader/extracted_articles.json`은 Jina Reader 실행 결과물입니다.
