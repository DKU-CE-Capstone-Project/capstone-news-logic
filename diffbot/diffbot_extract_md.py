"""
Diffbot Article API 결과를 Markdown 파일로만 저장하는 스크립트.

사용 예:
    python3 diffbot/diffbot_extract_md.py
    python3 diffbot/diffbot_extract_md.py "AI semiconductor" --diffbot-count 5
    python3 diffbot/diffbot_extract_md.py --url "https://example.com/news/article"
"""

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가합니다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402
from diffbot.diffbot_extract import (  # noqa: E402
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_INTERVAL_SECONDS,
    DIFFBOT_TOKEN_FILE,
    MAX_URLS,
    build_gdelt_params,
    call_diffbot_article,
    collect_direct_articles,
    collect_urls_from_gdelt,
    extract_primary_object,
    extract_with_local_fallback,
    load_token,
    normalize_diffbot_text,
    read_url_file,
    source_domain,
)
from test import (  # noqa: E402
    DEFAULT_MAX_RECORDS,
    DEFAULT_SEARCH_QUERY,
    DEFAULT_SORT,
    DEFAULT_SOURCE_LANG,
    DEFAULT_TIMESPAN,
)


OUTPUT_MD_FILE = Path(__file__).resolve().parent / "extracted_articles.md"


def normalize_inline(text: str) -> str:
    """Markdown 메타데이터에 넣을 한 줄 텍스트를 정리합니다."""
    return re.sub(r"\s+", " ", text or "").strip()


def escape_markdown_inline(text: str) -> str:
    """제목/메타데이터가 Markdown 문법으로 해석되지 않도록 이스케이프합니다."""
    text = normalize_inline(text)
    return re.sub(r"([\\`*_\[\]|])", r"\\\1", text)


def format_body(text: str) -> str:
    """Diffbot 본문 줄을 Markdown 문단으로 변환합니다."""
    paragraphs = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n\n".join(paragraphs)


def build_article_markdown(index: int, article: dict) -> str:
    title = escape_markdown_inline(article.get("title") or "(제목 없음)")
    url = normalize_inline(article.get("url", ""))
    source = normalize_inline(article.get("source_domain", ""))
    published_at = normalize_inline(article.get("published_at", ""))
    language = normalize_inline(article.get("language", ""))
    image_url = normalize_inline(article.get("image_url", ""))
    content = format_body(article.get("cleaned_content", ""))

    lines = [
        f"## {index}. {title}",
        "",
        f"- URL: <{url}>",
    ]
    if source:
        lines.append(f"- Source: {escape_markdown_inline(source)}")
    if published_at:
        lines.append(f"- Published: {escape_markdown_inline(published_at)}")
    if language:
        lines.append(f"- Language: {escape_markdown_inline(language)}")
    if image_url:
        lines.append(f"- Image: <{image_url}>")
    lines.extend([
        f"- Diffbot text length: {article.get('diffbot_text_length', 0)}",
        f"- Cleaned content length: {article.get('cleaned_content_length', 0)}",
        "",
        "### Body",
        "",
        content or "_본문 추출 실패_",
        "",
    ])
    return "\n".join(lines)


def build_failed_markdown(failed_results: list[dict]) -> str:
    if not failed_results:
        return ""

    lines = [
        "## Failed Results",
        "",
    ]
    for index, item in enumerate(failed_results, 1):
        title = escape_markdown_inline(item.get("title") or "(제목 없음)")
        url = normalize_inline(item.get("url", ""))
        error = escape_markdown_inline(item.get("error", ""))
        lines.extend([
            f"{index}. **{title}**",
            f"   - URL: <{url}>",
            f"   - Error: {error}",
            "",
        ])
    return "\n".join(lines)


def build_markdown_output(
    query: str,
    results: list[dict],
    failed_results: list[dict],
) -> str:
    extracted_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    lines = [
        "# Diffbot Extracted Articles",
        "",
        f"- Query: {escape_markdown_inline(query)}",
        f"- Extracted at: {escape_markdown_inline(extracted_at)}",
        f"- Success: {len(results)}",
        f"- Failed: {len(failed_results)}",
        "",
    ]
    for index, article in enumerate(results, 1):
        lines.append(build_article_markdown(index, article))

    failed_markdown = build_failed_markdown(failed_results)
    if failed_markdown:
        lines.append(failed_markdown)

    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GDELT 또는 직접 URL의 뉴스 기사를 Diffbot Article API로 추출해 Markdown으로만 저장합니다."
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
        default=OUTPUT_MD_FILE,
        help=f"결과 Markdown 저장 경로. 기본값: {OUTPUT_MD_FILE}",
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


def collect_input_articles(args: argparse.Namespace) -> tuple[str, list[dict]]:
    direct_urls = list(args.url)
    if args.url_file:
        direct_urls.extend(read_url_file(args.url_file))

    if direct_urls:
        print(f"직접 입력 URL {len(direct_urls)}개를 사용합니다.")
        return "direct-url", collect_direct_articles(direct_urls)

    request_params = build_gdelt_params(
        search_query=args.query,
        source_lang=args.source_lang,
        sort=args.sort,
        maxrecords=args.maxrecords,
        timespan=args.timespan,
    )
    print("=" * 60)
    print(" GDELT 기사 URL 수집 중...")
    print("=" * 60)
    return request_params["query"], collect_urls_from_gdelt(
        search_query=args.query,
        source_lang=args.source_lang,
        sort=args.sort,
        maxrecords=args.maxrecords,
        timespan=args.timespan,
    )


def extract_articles(args: argparse.Namespace, articles: list[dict], token: str) -> tuple[list[dict], list[dict]]:
    results = []
    failed_results = []

    print("\n" + "=" * 60)
    print(" Diffbot Article API 호출 중...")
    print("=" * 60)

    for index, article in enumerate(articles, 1):
        url = article["url"]
        if index > 1 and args.request_interval > 0:
            print(f"  다음 호출 전 {args.request_interval:g}초 대기...")
            time.sleep(args.request_interval)

        print(f"  [{index:02d}] {url} ... ", end="", flush=True)
        try:
            payload = call_diffbot_article(
                url=url,
                token=token,
                timeout_ms=args.timeout_ms,
                render_delay_ms=args.render_delay_ms,
                scroll=args.scroll,
                discussion=args.include_discussion,
                max_retries=max(0, args.max_retries),
            )
            obj = extract_primary_object(payload)
            diffbot_text = normalize_diffbot_text(obj.get("text", ""))
            title = article.get("title", "")
            cleaned = diffbot_text
            if not cleaned and args.fallback_local:
                cleaned = extract_with_local_fallback(url, title)
            print(f"{len(cleaned)}자 추출")

            results.append({
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

    return results, failed_results


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or [])
    request_query, articles = collect_input_articles(args)

    if not articles:
        print("수집된 기사 URL이 없습니다.")
        return

    articles = articles[:max(0, args.diffbot_count)]
    print(f"\nDiffbot Article API로 추출할 URL: {len(articles)}개\n")
    for index, article in enumerate(articles, 1):
        title = article.get("title") or "(제목 없음)"
        print(f"  [{index:02d}] {title}")
        print(f"       {article['url']}")

    try:
        token = load_token(args.token_file)
    except OSError as error:
        raise SystemExit(f"token 파일을 읽을 수 없습니다: {error}") from error
    except ValueError as error:
        raise SystemExit(str(error)) from error

    results, failed_results = extract_articles(args, articles, token)
    markdown = build_markdown_output(request_query, results, failed_results)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")

    print(f"\nMarkdown 결과가 저장되었습니다: {args.output}")
    print(f"성공: {len(results)}개 / 실패: {len(failed_results)}개")


if __name__ == "__main__":
    main(sys.argv[1:])
