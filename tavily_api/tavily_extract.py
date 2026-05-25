"""
Tavily Extract API를 사용하여 GDELT 기사 URL에서 본문을 추출하는 스크립트.

사용법:
    1. 검색어를 인자로 넘기면 GDELT에서 기사 목록을 가져옵니다.
       검색어를 생략하면 semiconductor를 사용합니다.
    2. GDELT 결과에서 중복 뉴스를 제거하고 상위 10개 URL을 수집해,
       Tavily /extract API를 호출하여 각 기사의 본문을 추출합니다.
    3. DOM 구조 기반 추출기와 trafilatura fallback으로 뉴스 본문만 정제합니다.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

import trafilatura
from bs4 import BeautifulSoup

# ── 프로젝트 루트를 import 경로에 추가 ──────────────────────────────
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

# ── 설정 ─────────────────────────────────────────────────────────────
ACTUALLY_CALL_API = True
MAX_URLS = 10
TAVILY_API_KEY_FILE = Path(__file__).resolve().parent / "key.txt"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
OUTPUT_FILE = Path(__file__).resolve().parent / "extracted_articles.json"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

CONTENT_ATTR_RE = re.compile(
    r"(article|articlebody|article-body|news[_-]?body|body|content|contents|"
    r"view|story|text|read|post|entry)",
    re.IGNORECASE,
)
STRONG_BODY_ATTR_RE = re.compile(
    r"(article[-_]?body|article[-_]?text|news[-_]?body|view[-_]?text|"
    r"content[-_]?body|story[-_]?body|post[-_]?content|entry[-_]?content)",
    re.IGNORECASE,
)
NOISE_ATTR_RE = re.compile(
    r"(^|[_\-\s])(ad|ads|advert|banner|comment|reply|related|recommend|"
    r"popular|ranking|rank|share|sns|social|footer|copyright|tag|keyword|"
    r"toolbar|pagination|subscribe|newsletter|login|menu|nav|notice|photo|"
    r"image|img|caption|live_re|livere)([_\-\s]|$)|view_ad|google|"
    r"outbrain|taboola",
    re.IGNORECASE,
)
BOILERPLATE_EXACT = {
    "증권 코드",
    "요약",
    "내용 컨텐츠",
    "관련기사",
    "댓글",
    "기자채널",
    "다른기사",
    "본문 글자 크기 조정",
    "글자 크게",
    "글자 작게",
}
BOILERPLATE_LINE_RE = re.compile(
    r"^(?:Copyright|<?저작권자|\[?\s*저작권자|무단\s*전재|댓글|제보전화|"
    r"회원가입|로그인|관련기사|기자채널|다른기사|프레시안에\s*제보|"
    r"취재\(|기타\(|#|\+|·|>Please activate JavaScript|"
    r"(?:입력|수정|송고시간|기사입력)\s*\d{4})",
    re.IGNORECASE,
)
CAPTION_LINE_RE = re.compile(
    r"^(?:[▲△].*|\[?그래픽.*|그래픽=.*|사진=.*|이미지=.*|"
    r"ChatGPT로 생성한 이미지.*|챗gpt를 이용해 제작함.*|"
    r".*\(출처=.*\)|.*제공\s*$|.*ⓒ.*)$",
    re.IGNORECASE,
)
EMAIL_ONLY_RE = re.compile(r"^[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}$")
MIN_ARTICLE_CHARS = 250
TRACKING_QUERY_PARAMS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "source",
}


def load_api_key() -> str:
    """key.txt에서 Tavily API 키를 읽어옵니다."""
    key = TAVILY_API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError(f"API 키가 비어 있습니다: {TAVILY_API_KEY_FILE}")
    return key


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
    """
    test.py의 fetch_gdelt_json()을 호출하여 기사 목록을 가져오고,
    중복을 제거한 뒤 각 기사의 title과 url을 반환합니다.
    """
    data = fetch_gdelt_json(
        search_query=search_query,
        source_lang=source_lang,
        sort=sort,
        maxrecords=maxrecords,
        timespan=timespan,
    )
    articles = data.get("articles", [])
    results = []
    for article in articles:
        url = article.get("url")
        if url:
            results.append({
                "title": article.get("title", "(제목 없음)"),
                "url": url,
                "source_domain": article.get("domain", ""),
                "published_at": article.get("seendate", ""),
                "language": article.get("language", "Korean"),
                "image_url": article.get("socialimage", ""),
            })
    return dedupe_articles(results)


def build_extract_request(urls: list[str], api_key: str) -> dict:
    """
    Tavily /extract API 요청 payload를 구성합니다.
    - depth: "basic"
    """
    return {
        "api_key": api_key,
        "urls": urls,
        "depth": "basic",
    }


def call_tavily_extract(payload: dict) -> dict:
    """Tavily /extract API를 호출하고 응답 JSON을 반환합니다."""
    response = requests.post(
        TAVILY_EXTRACT_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def normalize_space(text: str) -> str:
    """본문 비교와 저장에 사용할 공백을 단순화합니다."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def compact_text(text: str) -> str:
    """제목/중복 라인 비교용으로 공백을 제거합니다."""
    return re.sub(r"\s+", "", text or "").strip()


def text_signal_length(text: str) -> int:
    """기사성 텍스트의 대략적인 길이를 계산합니다."""
    return len(re.sub(r"[^0-9A-Za-z가-힣]", "", text or ""))


def element_attrs(element) -> str:
    """id/class/role처럼 레이아웃 의미가 담긴 속성을 하나의 문자열로 합칩니다."""
    values = []
    for attr in ("id", "class", "role", "aria-label"):
        value = element.get(attr)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value:
            values.append(str(value))
    return " ".join(values)


def collect_title_norms(soup: BeautifulSoup, title: str = "") -> set[str]:
    """본문에서 제외할 제목 후보를 수집합니다."""
    titles = [title] if title else []
    for selector in ("h1", 'meta[property="og:title"]', 'meta[name="twitter:title"]'):
        for element in soup.select(selector):
            if element.name == "meta":
                value = element.get("content")
            else:
                value = element.get_text(" ", strip=True)
            if value:
                titles.append(value)

    norms = set()
    for value in titles:
        for part in re.split(r"[-|｜:]", value):
            part = normalize_space(part)
            if len(compact_text(part)) >= 10:
                norms.add(compact_text(part))
        if len(compact_text(value)) >= 10:
            norms.add(compact_text(value))
    return norms


def remove_noise_nodes(soup: BeautifulSoup) -> None:
    """광고, 댓글, 공유 UI, 캡션 등 본문 밖 요소를 범용 규칙으로 제거합니다."""
    for tag in list(soup([
        "script",
        "style",
        "noscript",
        "iframe",
        "svg",
        "canvas",
        "form",
        "button",
        "input",
        "select",
        "textarea",
        "video",
        "audio",
        "table",
        "figure",
        "figcaption",
        "header",
        "footer",
        "nav",
        "aside",
    ])):
        tag.decompose()

    for element in list(soup.find_all(True)):
        if element.parent is None or element.name in ("html", "body"):
            continue

        attrs = element_attrs(element)
        if not NOISE_ATTR_RE.search(attrs):
            continue

        itemprop = str(element.get("itemprop") or "").lower()
        if "articlebody" in itemprop:
            continue
        if element.name == "article" and text_signal_length(element.get_text(" ", strip=True)) >= MIN_ARTICLE_CHARS:
            continue
        element.decompose()


def filter_article_line(line: str, title_norms: set[str]) -> str:
    """본문 라인에서 반복 제목, 캡션, 댓글/저작권 문구를 제외합니다."""
    line = normalize_space(line)
    if not line:
        return ""

    compact = compact_text(line)
    if compact in title_norms:
        return ""
    if line in BOILERPLATE_EXACT:
        return ""
    if len(compact) < 8:
        return ""
    if BOILERPLATE_LINE_RE.search(line):
        return ""
    if EMAIL_ONLY_RE.match(line):
        return ""
    if CAPTION_LINE_RE.match(line) and len(line) < 140:
        return ""
    return line


def collect_article_lines(element, title_norms: set[str]) -> list[str]:
    """선택한 DOM 요소에서 중복 없는 기사 라인을 추출합니다."""
    lines = []
    seen = set()
    for part in element.get_text("\n", strip=True).split("\n"):
        line = filter_article_line(part, title_norms)
        if not line:
            continue

        key = compact_text(line)
        if key in seen:
            continue

        seen.add(key)
        lines.append(line)
    return lines


def link_density(element) -> float:
    text_len = text_signal_length(element.get_text(" ", strip=True))
    if text_len == 0:
        return 1.0
    link_len = sum(text_signal_length(link.get_text(" ", strip=True)) for link in element.find_all("a"))
    return link_len / text_len


def score_article_candidate(element, lines: list[str]) -> int:
    text = "\n".join(lines)
    text_len = text_signal_length(text)
    if text_len < MIN_ARTICLE_CHARS:
        return -1

    attrs = element_attrs(element)
    itemprop = str(element.get("itemprop") or "").lower()
    punctuation_count = sum(text.count(mark) for mark in ".。!?다\"”")
    score = text_len + len(lines) * 80 + punctuation_count * 8

    if "articlebody" in itemprop:
        score += 5000
    if STRONG_BODY_ATTR_RE.search(attrs):
        score += 2500
    elif CONTENT_ATTR_RE.search(attrs):
        score += 500
    if element.name == "article":
        score += 1000

    score -= int(link_density(element) * text_len * 2)
    return score


def article_candidates(soup: BeautifulSoup, title: str = "") -> list[tuple[int, bool, bool, str]]:
    """기사 본문일 가능성이 있는 요소들을 점수순으로 반환합니다."""
    title_norms = collect_title_norms(soup, title)
    candidates = []

    for element in soup.find_all(["article", "main", "section", "div"]):
        if element.parent is None:
            continue

        attrs = element_attrs(element)
        itemprop = str(element.get("itemprop") or "").lower()
        is_candidate = (
            element.name in ("article", "main")
            or "articlebody" in itemprop
            or CONTENT_ATTR_RE.search(attrs)
        )
        if not is_candidate:
            continue

        lines = collect_article_lines(element, title_norms)
        score = score_article_candidate(element, lines)
        if score > 0:
            text = "\n".join(lines)
            is_semantic_body = "articlebody" in itemprop or bool(STRONG_BODY_ATTR_RE.search(attrs))
            is_itemprop_body = "articlebody" in itemprop
            candidates.append((score, is_semantic_body, is_itemprop_body, text))

    candidates.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return candidates


def extract_body_with_dom(html: str, title: str = "") -> str:
    """도메인별 하드코딩 없이 DOM 구조를 이용해 뉴스 본문을 추출합니다."""
    soup = BeautifulSoup(html, "lxml")
    remove_noise_nodes(soup)

    candidates = article_candidates(soup, title)
    if not candidates:
        return ""

    best_score, best_is_semantic, best_is_itemprop, best_text = candidates[0]
    best_compact = compact_text(best_text)

    if best_is_semantic and not best_is_itemprop:
        for _, _, _, candidate_text in candidates[1:]:
            candidate_compact = compact_text(candidate_text)
            if best_compact not in candidate_compact:
                continue
            if len(candidate_text) <= len(best_text) * 1.25:
                return candidate_text

    if best_score > 0:
        return best_text
    return ""


def extract_body_with_trafilatura_html(html: str) -> str:
    """trafilatura를 보조 추출기로 사용합니다."""
    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    )
    return extracted if extracted else ""


def extract_news_body(url: str, title: str = "") -> str:
    """
    뉴스 URL에서 본문만 추출합니다.
    1순위는 표준 articleBody/기사형 DOM 컨테이너, 2순위는 trafilatura입니다.
    """
    try:
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=30,
            allow_redirects=True,
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        html = response.text
    except requests.RequestException:
        html = trafilatura.fetch_url(url) or ""

    if not html:
        return ""

    dom_text = extract_body_with_dom(html, title)
    if dom_text:
        return dom_text

    return extract_body_with_trafilatura_html(html)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GDELT 기사 URL을 Tavily Extract API로 추출합니다."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=DEFAULT_SEARCH_QUERY,
        help=f"GDELT 검색어. 기본값: {DEFAULT_SEARCH_QUERY}",
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
        "--tavily-count",
        type=int,
        default=MAX_URLS,
        help=f"Tavily API에 보낼 중복 제거 후 기사 수. 기본값: {MAX_URLS}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv or [])
    request_params = build_gdelt_params(
        search_query=args.query,
        source_lang=args.source_lang,
        sort=args.sort,
        maxrecords=args.maxrecords,
        timespan=args.timespan,
    )

    # 1) GDELT 기사 URL 수집
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
        print("수집된 기사가 없습니다.")
        return

    print(f"\n중복 제거 후 총 {len(articles)}개 기사 URL 수집 완료:\n")
    for i, article in enumerate(articles, 1):
        print(f"  [{i:02d}] {article['title']}")
        print(f"       {article['url']}")
        print()

    # 2) Tavily Extract 요청 준비
    api_key = load_api_key()
    tavily_count = max(0, args.tavily_count)
    urls = [a["url"] for a in articles][:tavily_count]
    articles = articles[:tavily_count]
    print(f"→ 상위 {len(urls)}개 URL만 사용합니다.\n")
    payload = build_extract_request(urls, api_key)

    print("=" * 60)
    print(" Tavily /extract API 요청 payload (미리보기)")
    print("=" * 60)
    preview = {**payload, "api_key": payload["api_key"][:10] + "..."}
    print(json.dumps(preview, indent=2, ensure_ascii=False))
    print(f"\n요청 URL 개수: {len(urls)}")
    print(f"depth: {payload['depth']}")

    # 3) API 호출
    if not ACTUALLY_CALL_API:
        print("\n" + "=" * 60)
        print(" ⚠️  ACTUALLY_CALL_API = False 이므로 API 호출을 건너뜁니다.")
        print(" 실제 호출하려면 ACTUALLY_CALL_API = True 로 변경하세요.")
        print("=" * 60)
        return

    print("\n" + "=" * 60)
    print(" Tavily /extract API 호출 중...")
    print("=" * 60)

    try:
        result = call_tavily_extract(payload)
    except requests.RequestException as e:
        print(f"\nAPI 호출 실패: {e}")
        return

    # 4) 본문 정제
    print("\n" + "=" * 60)
    print(" 뉴스 본문 정제 중...")
    print("=" * 60)

    cleaned_results = []
    failed_results = []
    for idx, item in enumerate(result.get("results", []), 1):
        url = item.get("url", "")
        raw = item.get("raw_content", "")
        title = item.get("title", "")
        print(f"  [{idx:02d}] {url} ... ", end="", flush=True)
        source_article = next(
            (article for article in articles if article.get("url") == url),
            {},
        )
        try:
            cleaned = extract_news_body(url, title)
        except Exception as error:
            cleaned = ""
            failed_results.append({
                "url": url,
                "title": title,
                "error": str(error),
            })
        print(f"{len(cleaned)}자 추출")
        cleaned_results.append({
            "url": url,
            "title": title,
            "source_domain": source_article.get("source_domain", ""),
            "published_at": source_article.get("published_at", ""),
            "language": source_article.get("language", "Korean"),
            "image_url": source_article.get("image_url", ""),
            "raw_content_length": len(raw),
            "cleaned_content": cleaned,
            "cleaned_content_length": len(cleaned),
        })

    # 5) 정제 결과 저장
    output = {
        "query": request_params["query"],
        "total": len(cleaned_results),
        "results": cleaned_results,
        "failed_results": failed_results,
    }
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n정제된 결과가 저장되었습니다: {OUTPUT_FILE}")

    # 6) 결과 출력 (before/after 비교)
    print(f"\n성공적으로 추출된 기사 수: {len(cleaned_results)}\n")
    print("=" * 60)
    print(f" {'#':>3}  {'raw':>8} → {'cleaned':>8}  {'감소율':>6}  제목")
    print("=" * 60)

    for i, item in enumerate(cleaned_results, 1):
        raw_len = item["raw_content_length"]
        clean_len = item["cleaned_content_length"]
        reduction = (1 - clean_len / raw_len) * 100 if raw_len > 0 else 0
        title = item["title"][:40]
        print(f" {i:3d}  {raw_len:>8} → {clean_len:>8}  {reduction:>5.1f}%  {title}")

    # 7) 각 기사 본문 미리보기 출력
    print("\n" + "=" * 60)
    print(" 정제된 본문 미리보기 (앞 500자)")
    print("=" * 60)

    for i, item in enumerate(cleaned_results, 1):
        print(f"\n[{i:02d}] {item['title']}")
        print(f"     URL: {item['url']}")
        print(f"     본문 길이: {item['cleaned_content_length']}자")
        print("-" * 60)
        preview_text = item["cleaned_content"][:500]
        if preview_text:
            print(preview_text)
        else:
            print("     ⚠️ 본문 추출 실패")
        print("-" * 60)


if __name__ == "__main__":
    main(sys.argv[1:])
