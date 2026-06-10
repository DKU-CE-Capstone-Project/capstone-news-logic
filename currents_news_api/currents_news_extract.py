"""
Currents News API를 사용하여 test.py의 검색 입력값으로 뉴스 목록을 가져옵니다.

사용 예:
    python3 currents_news_api/currents_news_extract.py
    python3 currents_news_api/currents_news_extract.py "AI 반도체" --maxrecords 5

API key는 환경변수 CURRENTS_API_KEY 또는 currents_news_api/key.env에 저장합니다.
key.env 예:
    CURRENTS_API_KEY=your_api_key
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402
from test import (  # noqa: E402
    DEFAULT_MAX_RECORDS,
    DEFAULT_SEARCH_QUERY,
    DEFAULT_SORT,
    DEFAULT_SOURCE_LANG,
    DEFAULT_TIMESPAN,
    build_doc_query,
)


CURRENT_API_BASE_URL = "https://api.currentsapi.services"
CURRENT_API_KEY_FILE = Path(__file__).resolve().parent / "key.env"
OUTPUT_FILE = Path(__file__).resolve().parent / "extracted_articles.json"
TRACKING_QUERY_PARAMS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "source",
}
LANGUAGE_ALIASES = {
    "arabic": "ar",
    "chinese": "zh",
    "dutch": "nl",
    "english": "en",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "hindi": "hi",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
    "portuguese": "pt",
    "russian": "ru",
    "spanish": "es",
    "swedish": "sv",
    "turkish": "tr",
}


def source_domain(url: str) -> str:
    return urlparse(url or "").netloc.lower()


def normalize_title_key(title: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", (title or "").lower())


def normalize_url_key(url: str) -> str:
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


def load_api_key(api_key_file: Path = CURRENT_API_KEY_FILE) -> str:
    env_key = os.environ.get("CURRENTS_API_KEY") or os.environ.get("CURRENT_API_KEY")
    if env_key:
        return env_key.strip()

    if not api_key_file.exists():
        raise ValueError(
            "Currents API key가 필요합니다. "
            "CURRENTS_API_KEY 환경변수 또는 currents_news_api/key.env에 저장하세요."
        )

    raw_token = ""
    values = {}
    for raw_line in api_key_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raw_token = line
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

    api_key = (
        values.get("CURRENTS_API_KEY")
        or values.get("CURRENT_API_KEY")
        or values.get("API_KEY")
        or values.get("apiKey")
        or raw_token
    )
    if not api_key:
        raise ValueError(f"Currents API key 파일이 비어 있습니다: {api_key_file}")
    return api_key


def currents_language(source_lang: str) -> str:
    source_lang = (source_lang or "").strip().lower()
    return LANGUAGE_ALIASES.get(source_lang, source_lang or "en")


def timespan_to_start_date(timespan: str) -> str | None:
    if not timespan:
        return None

    match = re.fullmatch(r"\s*(\d+)\s*(s|m|h|d|w|mo|y)\s*", timespan.lower())
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    durations = {
        "s": timedelta(seconds=amount),
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
        "mo": timedelta(days=amount * 30),
        "y": timedelta(days=amount * 365),
    }
    start_date = datetime.now(timezone.utc) - durations[unit]
    return start_date.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clamp_page_size(value: int) -> int:
    return max(1, min(value, 300))


def build_currents_params(
    search_query: str = DEFAULT_SEARCH_QUERY,
    source_lang: str = DEFAULT_SOURCE_LANG,
    maxrecords: int = DEFAULT_MAX_RECORDS,
    timespan: str = DEFAULT_TIMESPAN,
    page_number: int = 1,
    country: str = "",
    category: str = "",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    params = {
        "keywords": (search_query or DEFAULT_SEARCH_QUERY).strip(),
        "language": currents_language(source_lang),
        "page_number": max(1, page_number),
        "page_size": clamp_page_size(maxrecords),
    }

    inferred_start_date = start_date or timespan_to_start_date(timespan)
    if inferred_start_date:
        params["start_date"] = inferred_start_date
    if end_date:
        params["end_date"] = end_date
    if country:
        params["country"] = country.upper()
    if category:
        params["category"] = category

    return params


def currents_search_endpoint(api_version: str) -> str:
    version = api_version.strip().lower()
    if version not in {"v1", "v2"}:
        raise ValueError("api_version은 v1 또는 v2만 사용할 수 있습니다.")
    return f"{CURRENT_API_BASE_URL}/{version}/search"


def call_currents_search(
    params: dict,
    api_key: str,
    api_version: str = "v1",
    timeout: int = 30,
) -> dict:
    response = requests.get(
        currents_search_endpoint(api_version),
        params=params,
        headers={
            "Authorization": api_key,
            "Accept": "application/json",
            "User-Agent": "capstone-currents-news-test/1.0",
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        detail = response.text.strip().replace(api_key, "<API_KEY>")
        if len(detail) > 300:
            detail = detail[:300] + "..."
        raise RuntimeError(f"Currents HTTP {response.status_code}: {detail}")

    payload = response.json()
    status = payload.get("status")
    if status and status != "ok":
        message = payload.get("message") or payload.get("msg") or payload.get("error") or status
        raise RuntimeError(f"Currents API error: {message}")
    return payload


def normalize_currents_articles(payload: dict) -> list[dict]:
    results = []
    for item in payload.get("news", []):
        url = item.get("url") or ""
        if not url:
            continue

        results.append({
            "title": item.get("title") or "(제목 없음)",
            "url": url,
            "source_domain": source_domain(url),
            "published_at": item.get("published", ""),
            "language": item.get("language", ""),
            "image_url": item.get("image") or "",
        })

    return dedupe_articles(results)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="test.py의 입력값을 Currents News API 검색에 적용합니다."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=DEFAULT_SEARCH_QUERY,
        help=f"검색어. 기본값: {DEFAULT_SEARCH_QUERY}",
    )
    parser.add_argument(
        "--source-lang",
        default=DEFAULT_SOURCE_LANG,
        help=f"언어 필터. test.py 기본값 {DEFAULT_SOURCE_LANG}은 Currents의 ko로 변환됩니다.",
    )
    parser.add_argument(
        "--sort",
        default=DEFAULT_SORT,
        help="test.py와의 CLI 호환용 옵션입니다. Currents Search API 요청에는 사용하지 않습니다.",
    )
    parser.add_argument(
        "--maxrecords",
        type=int,
        default=DEFAULT_MAX_RECORDS,
        help=f"Currents page_size로 보낼 기사 수. 기본값: {DEFAULT_MAX_RECORDS}",
    )
    parser.add_argument(
        "--timespan",
        default=DEFAULT_TIMESPAN,
        help=f"start_date로 변환할 기간. 기본값: {DEFAULT_TIMESPAN}",
    )
    parser.add_argument(
        "--start-date",
        default="",
        help="Currents start_date. 지정하면 --timespan 변환값보다 우선합니다.",
    )
    parser.add_argument(
        "--end-date",
        default="",
        help="Currents end_date.",
    )
    parser.add_argument(
        "--country",
        default="",
        help="2글자 국가 코드. 예: KR, US",
    )
    parser.add_argument(
        "--category",
        default="",
        help="카테고리. v1은 legacy, v2는 canonical category 값을 사용하세요.",
    )
    parser.add_argument(
        "--page-number",
        type=int,
        default=1,
        help="Currents page_number. 기본값: 1",
    )
    parser.add_argument(
        "--api-version",
        choices=("v1", "v2"),
        default="v1",
        help="Currents Search API 버전. 기본값: v1",
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=CURRENT_API_KEY_FILE,
        help=f"Currents API key 파일. 기본값: {CURRENT_API_KEY_FILE}",
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
        default=30,
        help="Currents API 요청 timeout(초). 기본값: 30",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or [])
    request_params = build_currents_params(
        search_query=args.query,
        source_lang=args.source_lang,
        maxrecords=args.maxrecords,
        timespan=args.timespan,
        page_number=args.page_number,
        country=args.country,
        category=args.category,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    request_query = build_doc_query(args.query, args.source_lang)

    print("=" * 60)
    print(" Currents News API 검색 요청")
    print("=" * 60)
    print(f"endpoint: {currents_search_endpoint(args.api_version)}")
    print(json.dumps(request_params, indent=2, ensure_ascii=False))
    if args.sort:
        print(f"\n참고: --sort {args.sort!r} 값은 Currents 요청에는 사용하지 않습니다.")

    try:
        api_key = load_api_key(args.api_key_file)
        payload = call_currents_search(
            request_params,
            api_key=api_key,
            api_version=args.api_version,
            timeout=args.timeout,
        )
    except (OSError, requests.RequestException, RuntimeError, ValueError) as error:
        raise SystemExit(f"error: {error}") from error

    articles = normalize_currents_articles(payload)
    output = {
        "query": request_query,
        "total": len(articles),
        "results": articles,
        "failed_results": [],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n결과가 저장되었습니다: {args.output}")
    print(f"수집된 기사: {len(articles)}개")

    print("\n" + "=" * 60)
    print(" Currents 결과 미리보기")
    print("=" * 60)
    for index, article in enumerate(articles, 1):
        print(f"\n[{index:02d}] {article['title']}")
        print(f"     URL: {article['url']}")
        print(f"     published: {article['published_at']}")
        print(f"     source: {article['source_domain']}")


if __name__ == "__main__":
    main(sys.argv[1:])
