import argparse
import hashlib
import json
import requests
import sys
import time
from pathlib import Path


MIN_REQUEST_INTERVAL_SECONDS = 12
CACHE_TTL_SECONDS = 86400
MAX_RETRIES = 5
CACHE_DIR = Path(".gdelt_cache")
LAST_REQUEST_FILE = CACHE_DIR / "test_last_request.txt"
DEFAULT_SEARCH_QUERY = "semiconductor"
DEFAULT_SOURCE_LANG = "korean"
DEFAULT_SORT = "hybridrel"
DEFAULT_MAX_RECORDS = 20
DEFAULT_TIMESPAN = "1d"

url = "https://api.gdeltproject.org/api/v2/doc/doc"

headers = {
    "User-Agent": "capstone-gdelt-doc-test/1.0",
    "Accept": "application/json",
}


def build_doc_query(search_query, source_lang=DEFAULT_SOURCE_LANG):
    search_query = (search_query or DEFAULT_SEARCH_QUERY).strip()
    if source_lang and "sourcelang:" not in search_query.lower():
        return f"{search_query} sourcelang:{source_lang}"
    return search_query


def build_gdelt_params(
    search_query=DEFAULT_SEARCH_QUERY,
    source_lang=DEFAULT_SOURCE_LANG,
    sort=DEFAULT_SORT,
    maxrecords=DEFAULT_MAX_RECORDS,
    timespan=DEFAULT_TIMESPAN,
):
    return {
        "query": build_doc_query(search_query, source_lang),
        "mode": "artlist",
        "format": "json",
        "sort": sort,
        "maxrecords": maxrecords,
        "timespan": timespan,
    }


params = build_gdelt_params()


def prepared_url(request_params=None):
    request = requests.Request("GET", url, params=request_params or params, headers=headers)
    return request.prepare().url


def cache_path(request_url):
    digest = hashlib.sha1(request_url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def read_cache(request_url):
    path = cache_path(request_url)
    if not path.exists():
        return None

    if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_cache(request_url, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with cache_path(request_url).open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def wait_for_request_slot():
    if not LAST_REQUEST_FILE.exists():
        return

    try:
        last_request_time = float(LAST_REQUEST_FILE.read_text(encoding="utf-8"))
    except ValueError:
        return

    wait_seconds = MIN_REQUEST_INTERVAL_SECONDS - (time.time() - last_request_time)
    if wait_seconds > 0:
        print(f"Waiting {wait_seconds:.1f} seconds to avoid GDELT rate limit...")
        time.sleep(wait_seconds)


def mark_request_time():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LAST_REQUEST_FILE.write_text(str(time.time()), encoding="utf-8")


def fetch_gdelt_json(
    search_query=DEFAULT_SEARCH_QUERY,
    source_lang=DEFAULT_SOURCE_LANG,
    sort=DEFAULT_SORT,
    maxrecords=DEFAULT_MAX_RECORDS,
    timespan=DEFAULT_TIMESPAN,
):
    request_params = build_gdelt_params(
        search_query=search_query,
        source_lang=source_lang,
        sort=sort,
        maxrecords=maxrecords,
        timespan=timespan,
    )
    request_url = prepared_url(request_params)
    cached = read_cache(request_url)
    if cached is not None:
        print("Using cached GDELT response.")
        return cached

    last_response = None
    for attempt in range(MAX_RETRIES):
        wait_for_request_slot()
        response = requests.get(url, params=request_params, headers=headers, timeout=20)
        mark_request_time()
        last_response = response

        if response.status_code != 429:
            response.raise_for_status()
            payload = response.json()
            write_cache(request_url, payload)
            return payload

        retry_after = response.headers.get("Retry-After")
        wait_seconds = (
            int(retry_after)
            if retry_after and retry_after.isdigit()
            else MIN_REQUEST_INTERVAL_SECONDS * (attempt + 1)
        )
        print(f"GDELT rate limit hit. Retrying in {wait_seconds} seconds...")
        if attempt < MAX_RETRIES - 1:
            time.sleep(wait_seconds)

    detail = last_response.text.strip() if last_response is not None else "No response"
    raise RuntimeError(f"GDELT rate limit exceeded after {MAX_RETRIES} retries: {detail}")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Fetch GDELT articles.")
    parser.add_argument(
        "query",
        nargs="?",
        default=DEFAULT_SEARCH_QUERY,
        help=f"Search keyword. Default: {DEFAULT_SEARCH_QUERY}",
    )
    parser.add_argument(
        "--source-lang",
        default=DEFAULT_SOURCE_LANG,
        help=f"GDELT sourcelang filter. Default: {DEFAULT_SOURCE_LANG}",
    )
    parser.add_argument(
        "--sort",
        default=DEFAULT_SORT,
        help=f"GDELT sort value. Default: {DEFAULT_SORT}",
    )
    parser.add_argument(
        "--maxrecords",
        type=int,
        default=DEFAULT_MAX_RECORDS,
        help=f"Number of GDELT articles to request. Default: {DEFAULT_MAX_RECORDS}",
    )
    parser.add_argument(
        "--timespan",
        default=DEFAULT_TIMESPAN,
        help=f"GDELT timespan. Default: {DEFAULT_TIMESPAN}",
    )
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    try:
        data = fetch_gdelt_json(
            search_query=args.query,
            source_lang=args.source_lang,
            sort=args.sort,
            maxrecords=args.maxrecords,
            timespan=args.timespan,
        )
    except (requests.RequestException, RuntimeError, ValueError) as error:
        raise SystemExit(f"error: {error}")

    for article in data.get("articles", []):
        print(article.get("title"))
        print(article.get("url"))
        print(article.get("seendate"))
        print(article.get("domain"))
        print("-" * 80)


if __name__ == "__main__":
    main(sys.argv[1:])
