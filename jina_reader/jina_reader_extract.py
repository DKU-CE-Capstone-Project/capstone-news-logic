"""
Jina Reader API를 사용하여 뉴스 기사 본문을 추출하는 스크립트.

사용 예:
    python3 jina_reader/jina_reader_extract.py
    python3 jina_reader/jina_reader_extract.py "AI semiconductor" --jina-count 5
    python3 jina_reader/jina_reader_extract.py --url "https://example.com/news/article"
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가합니다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402
from diffbot.diffbot_extract import (  # noqa: E402
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_INTERVAL_SECONDS,
    MAX_URLS,
    build_gdelt_params,
    collect_direct_articles,
    collect_urls_from_gdelt,
    read_url_file,
    retry_after_seconds,
    source_domain,
)
from test import (  # noqa: E402
    DEFAULT_MAX_RECORDS,
    DEFAULT_SEARCH_QUERY,
    DEFAULT_SORT,
    DEFAULT_SOURCE_LANG,
    DEFAULT_TIMESPAN,
)


JINA_READER_URL = "https://r.jina.ai/"
JINA_API_KEY_FILE = Path(__file__).resolve().parent / "key.txt"
OUTPUT_FILE = Path(__file__).resolve().parent / "extracted_articles.json"
JINA_CONTENT_HEADERS = {
    "Accept": "application/json",
}
DEFAULT_ENGINE = "browser"
DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_RESPOND_TIMING = "network-idle"
DEFAULT_RETAIN_IMAGES = "none"
DEFAULT_RETAIN_LINKS = "text"
DEFAULT_NO_CACHE = True
DEFAULT_DETACH_INVISIBLES = True
DEFAULT_TARGET_SELECTOR = (
    "article, main, [role='main'], #article, #articleBody, #article_body, "
    "#news_body, #newsContent, #news_content, .article_body, .article-body, "
    ".articleBody, .article_view, .article-view, .article-content, "
    ".article_view_content, .news_body, .news-body, .news_view, .news-content, "
    ".story-body, .view_body, .view-cont"
)
DEFAULT_REMOVE_SELECTOR = (
    "script, style, noscript, nav, header, footer, aside, form, iframe, "
    ".ad, .ads, .advertisement, .banner, .comment, .comments, .reply, "
    ".related, .recommend, .popular, .ranking, .share, .sns, .social, "
    ".newsletter, .subscribe, .login, .menu, .pagination, .tag, .keyword, "
    ".copyright, .toolbar, [class*='ad_'], [class*='ad-'], [id*='ad_'], "
    "[id*='ad-'], [class*='comment'], [id*='comment'], [class*='related'], "
    "[id*='related'], [class*='recommend'], [id*='recommend']"
)
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\([^)]+\)")
MARKDOWN_DECORATION_RE = re.compile(r"[*_`]+")
HEADER_LINE_RE = re.compile(r"^(?:Title|URL Source|Markdown Content):\s*", re.IGNORECASE)
BOILERPLATE_LINE_RE = re.compile(
    r"^(?:Copyright|<?저작권자|\[?\s*저작권자|무단\s*전재|댓글|제보전화|"
    r"회원가입|로그인|관련기사|기자채널|다른기사|프레시안에\s*제보|"
    r"취재\(|기타\(|#|\+|·|>Please activate JavaScript|"
    r"(?:입력|수정|송고시간|기사입력)\s*\d{4})",
    re.IGNORECASE,
)


def load_optional_api_key(api_key_file: Path = JINA_API_KEY_FILE) -> str:
    """Jina API key 파일이 있으면 읽고, 없으면 빈 문자열을 반환합니다."""
    if not api_key_file.exists():
        return ""
    key = api_key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError(f"Jina API key 파일이 비어 있습니다: {api_key_file}")
    return key


def normalize_space(text: str) -> str:
    """본문 저장에 사용할 공백을 단순화합니다."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def compact_text(text: str) -> str:
    """중복/제목 비교용으로 공백과 문장부호를 제거합니다."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text or "").lower()


def strip_markdown(text: str) -> str:
    """Jina Reader content의 Markdown 장식을 본문 텍스트로 정리합니다."""
    text = MARKDOWN_IMAGE_RE.sub("", text or "")
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text)
    text = re.sub(r"^\s{0,3}[-*+]\s+", "", text)
    text = re.sub(r"^\s{0,3}>\s?", "", text)
    return normalize_space(MARKDOWN_DECORATION_RE.sub("", text))


def normalize_jina_content(content: str, title: str = "") -> str:
    """
    Reader API의 본문 content만 Diffbot 결과처럼 plain text 문단으로 정리합니다.

    JSON 응답의 content 필드는 이미 Reader의 본문 추출 결과이지만, Markdown 이미지,
    링크 URL, 제목 중복, Reader 메타 헤더가 섞일 수 있어 최종 저장 전에 제거합니다.
    """
    title_keys = {compact_text(title)}
    paragraphs = []
    seen = set()

    for raw_line in (content or "").splitlines():
        if not raw_line.strip() or HEADER_LINE_RE.match(raw_line.strip()):
            continue

        line = strip_markdown(raw_line)
        if not line:
            continue
        if BOILERPLATE_LINE_RE.match(line):
            continue

        line_key = compact_text(line)
        if not line_key:
            continue
        if line_key in title_keys:
            continue
        if line_key in seen:
            continue

        seen.add(line_key)
        paragraphs.append(line)

    return "\n".join(paragraphs)


def build_reader_headers(
    api_key: str = "",
    engine: str | None = None,
    timeout_seconds: int | None = None,
    respond_timing: str | None = None,
    wait_for_selector: str | None = None,
    target_selector: str | None = None,
    remove_selector: str | None = None,
    retain_images: str | None = None,
    retain_links: str | None = None,
    detach_invisibles: bool = False,
    no_cache: bool = False,
) -> dict:
    headers = dict(JINA_CONTENT_HEADERS)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if engine:
        headers["X-Engine"] = engine
    if timeout_seconds is not None:
        headers["X-Timeout"] = str(timeout_seconds)
    if respond_timing:
        headers["X-Respond-Timing"] = respond_timing
    if wait_for_selector:
        headers["X-Wait-For-Selector"] = wait_for_selector
    if target_selector:
        headers["X-Target-Selector"] = target_selector
    if remove_selector:
        headers["X-Remove-Selector"] = remove_selector
    if retain_images:
        headers["X-Retain-Images"] = retain_images
    if retain_links:
        headers["X-Retain-Links"] = retain_links
    if detach_invisibles:
        headers["X-Detach-Invisibles"] = "true"
    if no_cache:
        headers["X-No-Cache"] = "true"
    return headers


def call_jina_reader(
    url: str,
    api_key: str = "",
    engine: str | None = None,
    timeout_seconds: int | None = None,
    respond_timing: str | None = None,
    wait_for_selector: str | None = None,
    target_selector: str | None = None,
    remove_selector: str | None = None,
    retain_images: str | None = None,
    retain_links: str | None = None,
    detach_invisibles: bool = False,
    no_cache: bool = False,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """Jina Reader API를 호출하고 응답 JSON을 반환합니다."""
    headers = build_reader_headers(
        api_key=api_key,
        engine=engine,
        timeout_seconds=timeout_seconds,
        respond_timing=respond_timing,
        wait_for_selector=wait_for_selector,
        target_selector=target_selector,
        remove_selector=remove_selector,
        retain_images=retain_images,
        retain_links=retain_links,
        detach_invisibles=detach_invisibles,
        no_cache=no_cache,
    )
    request_timeout = max(30, (timeout_seconds or 30) + 20)

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                JINA_READER_URL,
                data={"url": url},
                headers=headers,
                timeout=request_timeout,
            )
        except requests.RequestException as error:
            if attempt >= max_retries:
                raise
            wait_seconds = DEFAULT_REQUEST_INTERVAL_SECONDS * (attempt + 1)
            error_message = str(error).replace(api_key, "<API_KEY>") if api_key else str(error)
            print(f"\n       Jina Reader request failed: {error_message}")
            print(f"       {wait_seconds:.1f}초 후 재시도...")
            time.sleep(wait_seconds)
            continue

        if response.status_code == 429 and attempt < max_retries:
            wait_seconds = retry_after_seconds(response.headers.get("Retry-After"))
            if wait_seconds is None:
                wait_seconds = DEFAULT_REQUEST_INTERVAL_SECONDS * (attempt + 1)
            wait_seconds = max(1.0, wait_seconds)
            print(f"\n       Jina Reader rate limit. {wait_seconds:.1f}초 후 재시도...")
            time.sleep(wait_seconds)
            continue

        if response.status_code >= 400:
            detail = response.text.strip()
            if api_key:
                detail = detail.replace(api_key, "<API_KEY>")
            if len(detail) > 300:
                detail = detail[:300] + "..."
            raise RuntimeError(f"Jina Reader HTTP {response.status_code}: {detail}")

        payload = response.json()
        status_code = payload.get("code") or payload.get("status")
        if isinstance(status_code, int) and status_code >= 400:
            detail = payload.get("message") or payload.get("error") or status_code
            raise RuntimeError(f"Jina Reader API error: {detail}")
        return payload

    raise RuntimeError("Jina Reader API request failed after retries.")


def extract_reader_data(payload: dict) -> dict:
    """Jina Reader JSON 응답에서 data 객체를 꺼냅니다."""
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data[0] if data else {}
    if isinstance(data, dict):
        return data
    return {}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GDELT 또는 직접 URL의 뉴스 기사를 Jina Reader API로 추출합니다."
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
        help="Jina Reader로 바로 추출할 기사 URL. 여러 번 지정할 수 있습니다.",
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
        "--jina-count",
        type=int,
        default=MAX_URLS,
        help=f"Jina Reader API로 추출할 최대 기사 수. 기본값: {MAX_URLS}",
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=JINA_API_KEY_FILE,
        help=f"Jina API key 파일. 없으면 키 없이 호출합니다. 기본값: {JINA_API_KEY_FILE}",
    )
    parser.add_argument(
        "--require-api-key",
        action="store_true",
        help="api key 파일이 없거나 비어 있으면 실행을 중단합니다.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help=f"결과 JSON 저장 경로. 기본값: {OUTPUT_FILE}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Jina Reader가 대상 페이지 로드를 기다릴 시간(초). 기본값: {DEFAULT_TIMEOUT_SECONDS}",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "browser", "curl"),
        default=DEFAULT_ENGINE,
        help=f"Jina Reader fetch engine. 기본값: {DEFAULT_ENGINE}",
    )
    parser.add_argument(
        "--respond-timing",
        choices=(
            "html",
            "visible-content",
            "mutation-idle",
            "resource-idle",
            "media-idle",
            "network-idle",
        ),
        default=DEFAULT_RESPOND_TIMING,
        help=f"Reader 응답 시점. 기본값: {DEFAULT_RESPOND_TIMING}",
    )
    parser.add_argument(
        "--wait-for-selector",
        help="동적 본문 로딩을 기다릴 CSS selector.",
    )
    parser.add_argument(
        "--target-selector",
        default=DEFAULT_TARGET_SELECTOR,
        help="이 CSS selector 내부만 Reader 결과로 받습니다. 기본값은 뉴스 본문 컨테이너 후보입니다.",
    )
    parser.add_argument(
        "--remove-selector",
        default=DEFAULT_REMOVE_SELECTOR,
        help="Reader 결과에서 제거할 CSS selector. 기본값은 메뉴/광고/댓글/관련기사 후보입니다.",
    )
    parser.add_argument(
        "--retain-images",
        choices=("all", "none", "alt"),
        default=DEFAULT_RETAIN_IMAGES,
        help=f"Reader 결과에 이미지를 남기는 방식. 기본값: {DEFAULT_RETAIN_IMAGES}",
    )
    parser.add_argument(
        "--retain-links",
        choices=("all", "none", "text", "gpt-oss"),
        default=DEFAULT_RETAIN_LINKS,
        help=f"Reader 결과에 링크를 남기는 방식. 기본값: {DEFAULT_RETAIN_LINKS}",
    )
    invisibles_group = parser.add_mutually_exclusive_group()
    invisibles_group.add_argument(
        "--detach-invisibles",
        dest="detach_invisibles",
        action="store_true",
        default=DEFAULT_DETACH_INVISIBLES,
        help="Jina Reader에서 숨겨진 DOM 요소를 제거합니다. 기본값입니다.",
    )
    invisibles_group.add_argument(
        "--keep-invisibles",
        dest="detach_invisibles",
        action="store_false",
        help="Jina Reader에서 숨겨진 DOM 요소를 유지합니다.",
    )
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        default=DEFAULT_NO_CACHE,
        help="Jina Reader 캐시를 우회합니다. 기본값입니다.",
    )
    cache_group.add_argument(
        "--use-cache",
        dest="no_cache",
        action="store_false",
        help="Jina Reader 캐시 사용을 허용합니다.",
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL_SECONDS,
        help=f"Jina Reader 호출 사이 대기 시간(초). 기본값: {DEFAULT_REQUEST_INTERVAL_SECONDS:g}",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"429 응답 재시도 횟수. 기본값: {DEFAULT_MAX_RETRIES}",
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

    count = max(0, args.jina_count)
    articles = articles[:count]
    print(f"\nJina Reader API로 추출할 URL: {len(articles)}개\n")
    for i, article in enumerate(articles, 1):
        title = article.get("title") or "(제목 없음)"
        print(f"  [{i:02d}] {title}")
        print(f"       {article['url']}")

    try:
        api_key = load_optional_api_key(args.api_key_file)
    except OSError as error:
        raise SystemExit(f"api key 파일을 읽을 수 없습니다: {error}") from error
    except ValueError as error:
        raise SystemExit(str(error)) from error

    if args.require_api_key and not api_key:
        raise SystemExit(f"Jina API key 파일이 필요합니다: {args.api_key_file}")

    cleaned_results = []
    failed_results = []

    print("\n" + "=" * 60)
    print(" Jina Reader API 호출 중...")
    print("=" * 60)

    for idx, article in enumerate(articles, 1):
        url = article["url"]
        if idx > 1 and args.request_interval > 0:
            print(f"  다음 호출 전 {args.request_interval:g}초 대기...")
            time.sleep(args.request_interval)
        print(f"  [{idx:02d}] {url} ... ", end="", flush=True)
        try:
            payload = call_jina_reader(
                url=url,
                api_key=api_key,
                engine=args.engine,
                timeout_seconds=args.timeout,
                respond_timing=args.respond_timing,
                wait_for_selector=args.wait_for_selector,
                target_selector=args.target_selector,
                remove_selector=args.remove_selector,
                retain_images=args.retain_images,
                retain_links=args.retain_links,
                detach_invisibles=args.detach_invisibles,
                no_cache=args.no_cache,
                max_retries=max(0, args.max_retries),
            )
            data = extract_reader_data(payload)
            reader_title = data.get("title") or ""
            title = article.get("title") or reader_title
            reader_content = data.get("content") or data.get("text") or ""
            cleaned = normalize_jina_content(reader_content, title)
            print(f"{len(cleaned)}자 추출")

            cleaned_results.append({
                "url": url,
                "title": title,
                "source_domain": article.get("source_domain") or source_domain(url),
                "published_at": article.get("published_at") or data.get("publishedTime") or "",
                "language": article.get("language", ""),
                "image_url": article.get("image_url", ""),
                "jina_title": reader_title,
                "jina_content_length": len(reader_content),
                "cleaned_content": cleaned,
                "cleaned_content_length": len(cleaned),
            })
        except (requests.RequestException, RuntimeError, ValueError) as error:
            error_message = str(error).replace(api_key, "<API_KEY>") if api_key else str(error)
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
