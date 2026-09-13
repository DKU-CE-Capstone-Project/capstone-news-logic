"""
Diffbot Article API를 사용하여 뉴스 기사 본문을 추출하는 스크립트.

사용 예:
    python3 diffbot/diffbot_extract.py
    python3 diffbot/diffbot_extract.py "AI semiconductor" --diffbot-count 5
    python3 diffbot/diffbot_extract.py --url "https://example.com/news/article"
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

# 프로젝트 루트를 import 경로에 추가합니다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402
from test import (  # noqa: E402
    DEFAULT_MAX_RECORDS,
    DEFAULT_SEARCH_QUERY,
    DEFAULT_SORT,
    DEFAULT_SOURCE_LANG,
    DEFAULT_TIMESPAN,
    build_gdelt_params,
    fetch_gdelt_json,
)


MAX_URLS = 10
DEFAULT_REQUEST_INTERVAL_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 3
DIFFBOT_TOKEN_FILE = Path(__file__).resolve().parent / "token.txt"
DIFFBOT_ARTICLE_URL = "https://api.diffbot.com/v3/article"
OUTPUT_FILE = Path(__file__).resolve().parent / "extracted_articles.json"
TRACKING_QUERY_PARAMS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "source",
}


def load_token(token_file: Path = DIFFBOT_TOKEN_FILE) -> str:
    """Diffbot API token을 파일에서 읽어옵니다."""
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError(f"Diffbot API token 파일이 비어 있습니다: {token_file}")
    return token


def read_url_file(path: Path) -> list[str]:
    """한 줄에 하나씩 저장된 기사 URL 파일을 읽습니다."""
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            urls.append(value)
    return urls


def source_domain(url: str) -> str:
    return urlparse(url or "").netloc.lower()


def normalize_space(text: str) -> str:
    """본문 저장에 사용할 공백을 단순화합니다."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def normalize_diffbot_text(text: str) -> str:
    """Diffbot text 필드의 문단 구조를 유지하면서 공백을 정리합니다."""
    paragraphs = []
    for line in (text or "").splitlines():
        line = normalize_space(line)
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def retry_after_seconds(value: str | None) -> float | None:
    """Retry-After 헤더를 초 단위로 변환합니다."""
    if not value:
        return None

    value = value.strip()
    if value.isdigit():
        return float(value)

    duration_match = re.fullmatch(
        r"(?:(\d+)\s+days?,\s*)?(\d{1,2}):(\d{2}):(\d{2})",
        value,
        re.IGNORECASE,
    )
    if duration_match:
        days = int(duration_match.group(1) or 0)
        hours = int(duration_match.group(2))
        minutes = int(duration_match.group(3))
        seconds = int(duration_match.group(4))
        return float(days * 86400 + hours * 3600 + minutes * 60 + seconds)

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def normalize_title_key(title: str) -> str:
    """중복 기사 판단에 사용할 제목 키를 만듭니다."""
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", (title or "").lower())


def normalize_url_key(url: str) -> str:
    """모바일/웹 도메인과 추적 파라미터 차이를 줄인 URL 키를 만듭니다."""
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break

    query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key.startswith("utm_") or lower_key in TRACKING_QUERY_PARAMS:
            continue
        query_pairs.append((key, value))

    path = parsed.path.rstrip("/") or parsed.path
    query = urlencode(sorted(query_pairs))
    return f"{host}{path}?{query}" if query else f"{host}{path}"


def dedupe_articles(articles: list[dict]) -> list[dict]:
    """GDELT 결과에서 같은 뉴스로 보이는 항목을 제거합니다."""
    unique_articles = []
    seen_urls = set()
    seen_titles = set()

    for article in articles:
        url_key = normalize_url_key(article.get("url", ""))
        title_key = normalize_title_key(article.get("title", ""))

        if url_key and url_key in seen_urls:
            continue
        if len(title_key) >= 12 and title_key in seen_titles:
            continue

        if url_key:
            seen_urls.add(url_key)
        if len(title_key) >= 12:
            seen_titles.add(title_key)
        unique_articles.append(article)

    return unique_articles


def collect_urls_from_gdelt(
    search_query: str = DEFAULT_SEARCH_QUERY,
    source_lang: str = DEFAULT_SOURCE_LANG,
    sort: str = DEFAULT_SORT,
    maxrecords: int = DEFAULT_MAX_RECORDS,
    timespan: str = DEFAULT_TIMESPAN,
) -> list[dict]:
    """GDELT 기사 목록을 가져오고 Diffbot 입력 메타데이터로 변환합니다."""
    data = fetch_gdelt_json(
        search_query=search_query,
        source_lang=source_lang,
        sort=sort,
        maxrecords=maxrecords,
        timespan=timespan,
    )
    results = []
    for article in data.get("articles", []):
        url = article.get("url")
        if not url:
            continue
        results.append({
            "title": article.get("title", "(제목 없음)"),
            "url": url,
            "source_domain": article.get("domain", ""),
            "published_at": article.get("seendate", ""),
            "language": article.get("language", "Korean"),
            "image_url": article.get("socialimage", ""),
        })
    return dedupe_articles(results)


def extract_with_local_fallback(url: str, title: str = "") -> str:
    """필요할 때만 기존 로컬 추출기를 로드해 Diffbot 실패를 보완합니다."""
    from tavily_api.tavily_extract import extract_news_body  # noqa: PLC0415

    return extract_news_body(url, title)


def build_article_params(
    url: str,
    token: str,
    timeout_ms: int,
    render_delay_ms: int | None = None,
    scroll: str | None = None,
    discussion: bool = False,
    use_proxy: bool = False,
    natural_language: str | None = None,
) -> dict:
    params = {
        "token": token,
        "url": url,
        "timeout": timeout_ms,
        "discussion": str(discussion).lower(),
    }
    if use_proxy:
        params["useProxy"] = "default"
    if natural_language:
        params["naturalLanguage"] = natural_language
    if render_delay_ms is not None:
        params["renderDelay"] = render_delay_ms
    if scroll:
        params["scroll"] = scroll
    return params


def call_diffbot_article(
    url: str,
    token: str,
    timeout_ms: int = 30000,
    render_delay_ms: int | None = None,
    scroll: str | None = None,
    discussion: bool = False,
    use_proxy: bool = False,
    natural_language: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """Diffbot Article API를 호출하고 응답 JSON을 반환합니다."""
    request_params = build_article_params(
        url=url,
        token=token,
        timeout_ms=timeout_ms,
        render_delay_ms=render_delay_ms,
        scroll=scroll,
        discussion=discussion,
        use_proxy=use_proxy,
        natural_language=natural_language,
    )
    timeout_seconds = max(30, int(timeout_ms / 1000) + 20)

    for attempt in range(max_retries + 1):
        try:
            response = requests.get(
                DIFFBOT_ARTICLE_URL,
                params=request_params,
                timeout=timeout_seconds,
            )
        except requests.RequestException as error:
            if attempt >= max_retries:
                raise
            wait_seconds = DEFAULT_REQUEST_INTERVAL_SECONDS * (attempt + 1)
            error_message = str(error).replace(token, "<TOKEN>")
            print(f"\n       Diffbot request failed: {error_message}")
            print(f"       {wait_seconds:.1f}초 후 재시도...")
            time.sleep(wait_seconds)
            continue

        if response.status_code == 429 and attempt < max_retries:
            wait_seconds = retry_after_seconds(response.headers.get("Retry-After"))
            if wait_seconds is None:
                wait_seconds = DEFAULT_REQUEST_INTERVAL_SECONDS * (attempt + 1)
            wait_seconds = max(1.0, wait_seconds)
            print(f"\n       Diffbot rate limit. {wait_seconds:.1f}초 후 재시도...")
            time.sleep(wait_seconds)
            continue

        if response.status_code >= 400:
            detail = response.text.strip().replace(token, "<TOKEN>")
            if len(detail) > 300:
                detail = detail[:300] + "..."
            raise RuntimeError(f"Diffbot HTTP {response.status_code}: {detail}")

        payload = response.json()
        if payload.get("error") or payload.get("errorCode"):
            detail = payload.get("error") or payload.get("message") or payload.get("errorCode")
            raise RuntimeError(f"Diffbot API error: {detail}")
        return payload

    raise RuntimeError("Diffbot API request failed after retries.")


def extract_primary_object(payload: dict) -> dict:
    objects = payload.get("objects") or []
    if not objects:
        return {}
    return objects[0]


def collect_direct_articles(urls: list[str]) -> list[dict]:
    """직접 전달된 URL을 기존 출력 메타데이터 형태로 맞춥니다."""
    return [
        {
            "title": "",
            "url": url,
            "source_domain": source_domain(url),
            "published_at": "",
            "language": "",
            "image_url": "",
        }
        for url in urls
    ]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GDELT 또는 직접 URL의 뉴스 기사를 Diffbot Article API로 추출합니다."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=DEFAULT_SEARCH_QUERY,
        help=f"GDELT 검색어. --url/--url-file 사용 시 무시됩니다. 기본값: {DEFAULT_SEARCH_QUERY}",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Diffbot으로 바로 추출할 기사 URL. 여러 번 지정할 수 있습니다.",
    )
    parser.add_argument(
        "--url-file",
        type=Path,
        help="한 줄에 하나씩 기사 URL이 들어 있는 파일.",
    )
    parser.add_argument(
        "--source-lang",
        default=DEFAULT_SOURCE_LANG,
        help=f"GDELT sourcelang 필터. 기본값: {DEFAULT_SOURCE_LANG}",
    )
    parser.add_argument(
        "--sort",
        default=DEFAULT_SORT,
        help=f"GDELT 정렬값. 기본값: {DEFAULT_SORT}",
    )
    parser.add_argument(
        "--maxrecords",
        type=int,
        default=DEFAULT_MAX_RECORDS,
        help=f"GDELT에서 가져올 기사 수. 기본값: {DEFAULT_MAX_RECORDS}",
    )
    parser.add_argument(
        "--timespan",
        default=DEFAULT_TIMESPAN,
        help=f"GDELT 검색 기간. 기본값: {DEFAULT_TIMESPAN}",
    )
    parser.add_argument(
        "--diffbot-count",
        type=int,
        default=MAX_URLS,
        help=f"Diffbot API로 추출할 최대 기사 수. 기본값: {MAX_URLS}",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=DIFFBOT_TOKEN_FILE,
        help=f"Diffbot API token 파일. 기본값: {DIFFBOT_TOKEN_FILE}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help=f"결과 JSON 저장 경로. 기본값: {OUTPUT_FILE}",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Diffbot이 대상 페이지 응답을 기다릴 시간(ms). 기본값: 30000",
    )
    parser.add_argument(
        "--render-delay-ms",
        type=int,
        help="자바스크립트 렌더링 후 추가 대기 시간(ms).",
    )
    parser.add_argument(
        "--scroll",
        choices=("slow", "fast"),
        help="lazy-load 본문이 있는 페이지에서 Diffbot 브라우저 스크롤을 지정합니다.",
    )
    parser.add_argument(
        "--include-discussion",
        action="store_true",
        help="기사 댓글/토론 추출을 포함합니다. 기본은 본문만 추출하기 위해 제외합니다.",
    )
    parser.add_argument(
        "--use-proxy",
        action="store_true",
        help="Diffbot 데이터센터 프록시를 사용합니다(useProxy=default).",
    )
    parser.add_argument(
        "--natural-language",
        nargs="?",
        const="entities,facts,categories,sentiment,language",
        help=(
            "Diffbot Natural Language 분석을 실행합니다. 값 없이 쓰면 "
            "entities,facts,categories,sentiment,language를 요청합니다."
        ),
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL_SECONDS,
        help=f"Diffbot 호출 사이 대기 시간(초). 기본값: {DEFAULT_REQUEST_INTERVAL_SECONDS:g}",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"429 응답 재시도 횟수. 기본값: {DEFAULT_MAX_RETRIES}",
    )
    parser.add_argument(
        "--fallback-local",
        action="store_true",
        help="Diffbot text가 비어 있을 때 기존 로컬 DOM/trafilatura 추출기를 한 번 더 시도합니다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or [])
    direct_urls = list(args.url)
    if args.url_file:
        direct_urls.extend(read_url_file(args.url_file))

    if direct_urls:
        request_query = "direct-url"
        articles = collect_direct_articles(direct_urls)
        print(f"직접 입력 URL {len(articles)}개를 사용합니다.")
    else:
        request_params = build_gdelt_params(
            search_query=args.query,
            source_lang=args.source_lang,
            sort=args.sort,
            maxrecords=args.maxrecords,
            timespan=args.timespan,
        )
        request_query = request_params["query"]
        print("=" * 60)
        print(" GDELT 기사 URL 수집 중...")
        print("=" * 60)
        articles = collect_urls_from_gdelt(
            search_query=args.query,
            source_lang=args.source_lang,
            sort=args.sort,
            maxrecords=args.maxrecords,
            timespan=args.timespan,
        )

    if not articles:
        print("수집된 기사 URL이 없습니다.")
        return

    count = max(0, args.diffbot_count)
    articles = articles[:count]
    print(f"\nDiffbot Article API로 추출할 URL: {len(articles)}개\n")
    for i, article in enumerate(articles, 1):
        title = article.get("title") or "(제목 없음)"
        print(f"  [{i:02d}] {title}")
        print(f"       {article['url']}")

    try:
        token = load_token(args.token_file)
    except OSError as error:
        raise SystemExit(f"token 파일을 읽을 수 없습니다: {error}") from error
    except ValueError as error:
        raise SystemExit(str(error)) from error

    cleaned_results = []
    failed_results = []

    print("\n" + "=" * 60)
    print(" Diffbot Article API 호출 중...")
    print("=" * 60)

    for idx, article in enumerate(articles, 1):
        url = article["url"]
        if idx > 1 and args.request_interval > 0:
            print(f"  다음 호출 전 {args.request_interval:g}초 대기...")
            time.sleep(args.request_interval)
        print(f"  [{idx:02d}] {url} ... ", end="", flush=True)
        try:
            payload = call_diffbot_article(
                url=url,
                token=token,
                timeout_ms=args.timeout_ms,
                render_delay_ms=args.render_delay_ms,
                scroll=args.scroll,
                discussion=args.include_discussion,
                use_proxy=args.use_proxy,
                natural_language=args.natural_language,
                max_retries=max(0, args.max_retries),
            )
            obj = extract_primary_object(payload)
            diffbot_text = normalize_diffbot_text(obj.get("text", ""))
            title = article.get("title", "")
            cleaned = diffbot_text
            if not cleaned and args.fallback_local:
                cleaned = extract_with_local_fallback(url, title)
            print(f"{len(cleaned)}자 추출")

            cleaned_results.append({
                "url": url,
                "title": title,
                "source_domain": article.get("source_domain") or source_domain(url),
                "published_at": article.get("published_at", ""),
                "language": article.get("language", ""),
                "image_url": article.get("image_url", ""),
                "diffbot_text_length": len(diffbot_text),
                "cleaned_content": cleaned,
                "cleaned_content_length": len(cleaned),
            })
        except (requests.RequestException, RuntimeError, ValueError) as error:
            error_message = str(error).replace(token, "<TOKEN>")
            print(f"실패: {error_message}")
            failed_results.append({
                "url": url,
                "title": article.get("title", ""),
                "error": error_message,
            })

    output = {
        "query": request_query,
        "total": len(cleaned_results),
        "results": cleaned_results,
        "failed_results": failed_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n결과가 저장되었습니다: {args.output}")
    print(f"성공: {len(cleaned_results)}개 / 실패: {len(failed_results)}개")

    print("\n" + "=" * 60)
    print(" 추출 본문 미리보기 (앞 500자)")
    print("=" * 60)
    for i, item in enumerate(cleaned_results, 1):
        print(f"\n[{i:02d}] {item['title']}")
        print(f"     URL: {item['url']}")
        print(f"     본문 길이: {item['cleaned_content_length']}자")
        print("-" * 60)
        print(item["cleaned_content"][:500] or "본문 추출 실패")
        print("-" * 60)


if __name__ == "__main__":
    main(sys.argv[1:])
