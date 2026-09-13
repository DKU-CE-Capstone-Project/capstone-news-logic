"""Stable backend interface over the same implementations used by the CLI."""
import asyncio
import logging
from typing import Any

from diffbot.diffbot_extract import collect_urls_from_gdelt
from capstone_news_logic import gdelt

log = logging.getLogger(__name__)


def build_gdelt_params(search_query="semiconductor", source_lang="korean",
                       sort="hybridrel", maxrecords=10, timespan="1d"):
    return gdelt.build_gdelt_params(search_query, source_lang, sort, maxrecords, timespan)


async def fetch_gdelt_articles(keyword: str, source_lang: str = "korean",
                               maxrecords: int = 10, timespan: str = "1d") -> list[dict[str, Any]]:
    try:
        return await asyncio.to_thread(
            collect_urls_from_gdelt, search_query=keyword, source_lang=source_lang,
            maxrecords=maxrecords, timespan=timespan,
        )
    except Exception:
        log.exception("GDELT search failed")
        return []
