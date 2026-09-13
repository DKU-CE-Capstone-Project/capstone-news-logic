from capstone_news_logic import api, gdelt
from diffbot import diffbot_extract


async def test_search_uses_shared_cli_logic(monkeypatch):
    calls = {}
    def fetch(**kwargs):
        calls.update(kwargs)
        return {"articles": [
            {"title": "Shared news headline", "url": "https://www.example.com/a?utm_source=x", "domain": "example.com", "seendate": "20260913T010203Z", "socialimage": "https://example.com/image.jpg"},
            {"title": "Shared news headline", "url": "https://m.example.com/a"},
            {"title": "No URL"},
        ]}
    monkeypatch.setattr(diffbot_extract, "fetch_gdelt_json", fetch)
    articles = await api.fetch_gdelt_articles("AI", maxrecords=5)
    assert calls["search_query"] == "AI" and calls["maxrecords"] == 5
    assert len(articles) == 1
    assert articles[0]["image_url"] == "https://example.com/image.jpg"
    assert articles[0]["published_at"] == "20260913T010203Z"


async def test_provider_failure_allows_backend_fallback(monkeypatch):
    def fail(**kwargs):
        raise ValueError("Invalid provider response")
    monkeypatch.setattr(diffbot_extract, "fetch_gdelt_json", fail)
    assert await api.fetch_gdelt_articles("AI") == []


def test_language_filter_is_not_duplicated():
    assert gdelt.build_doc_query("AI sourcelang:english") == "AI sourcelang:english"
