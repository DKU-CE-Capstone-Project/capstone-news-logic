# 본문 일치 검증

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
