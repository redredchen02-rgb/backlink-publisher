# ko_corpus fixture manifest

Provenance record for `tests/fixtures/ko_corpus/`, collected 2026-07-02 for
Sprint D3 (`ko-corpus-calibration`, `debt_registry.toml`) of
`docs/plans/2026-06-30-001-opt-phase3-post-v050-iteration-plan.md`.

All text was fetched from genuinely public web pages (no auth, no paywall)
via automated fetch-and-extract. Each sample is the article/post body only
(navigation, ads, and comment sections stripped as best-effort). Some
samples retain the source's inline markdown-link syntax (`[text](url)`)
produced by the fetch tool's HTML-to-markdown conversion — this is left
intentionally, since the language-detection module's real input shape is
markdown/HTML source text with exactly that noise, and `_strip_noise()`
is designed to strip it before scoring.

**Collection floor note**: the plan asked for "~50" real samples with a
documented floor of ~20-30 if 50 was impractical in-session. 31 positive +
7 negative-control samples were collected; going further would have meant
either re-fetching near-duplicate content from the same handful of
JS-rendered sites (Naver Blog, most of `chosun.com`/`hani.co.kr`, and
`namu.wiki` all either render content client-side via iframe/JS or return
HTTP 403 to the fetch tool) or padding with synthetic text, both of which
the task explicitly ruled out.

## Positive corpus (`positive/`, N=31) — real Korean text

| file | source | type | notes |
|---|---|---|---|
| ko_001_wiki_daehanminguk.txt | https://ko.wikipedia.org/wiki/대한민국 | Encyclopedia | country overview |
| ko_002_wiki_sejong.txt | https://ko.wikipedia.org/wiki/세종대왕 | Encyclopedia | historical figure |
| ko_003_wiki_hunminjeongeum.txt | https://ko.wikipedia.org/wiki/훈민정음 | Encyclopedia | Hanja-dense (script history) |
| ko_004_wiki_yisunsin.txt | https://ko.wikipedia.org/wiki/이순신 | Encyclopedia | most Hanja-dense sample collected (military-rank glosses) |
| ko_005_wiki_kimchi.txt | https://ko.wikipedia.org/wiki/김치 | Encyclopedia | food/culture |
| ko_006_news_ohmynews_citizen_reporter.txt | https://www.ohmynews.com/NWS_Web/View/at_pg.aspx?CNTN_CD=A0003185178 | News (citizen journalism) | OhmyNews personal-essay-style article |
| ko_007_news_travie_2026_travel_trends.txt | https://www.travie.com/news/articleView.html?idxno=55124 | News (magazine) | travel-trend listicle |
| ko_008_wiki_ingongjineung.txt | https://ko.wikipedia.org/wiki/인공지능 | Encyclopedia | technology, Hanja term in lead |
| ko_009_wiki_seoul.txt | https://ko.wikipedia.org/wiki/서울특별시 | Encyclopedia | geography/history |
| ko_010_wiki_son_heungmin.txt | https://ko.wikipedia.org/wiki/손흥민 | Encyclopedia | sports biography |
| ko_011_news_khan_opinion.txt | https://www.khan.co.kr/opinion | News (editorial) | Kyunghyang Shinmun opinion excerpt |
| ko_012_wiki_bulgyo.txt | https://ko.wikipedia.org/wiki/불교 | Encyclopedia | Hanja-dense (religion/philosophy) |
| ko_013_wiki_constitution.txt | https://ko.wikipedia.org/wiki/대한민국_헌법 | Encyclopedia | legal/administrative register |
| ko_014_wiki_korean_war.txt | https://ko.wikipedia.org/wiki/6.25_전쟁 | Encyclopedia | history |
| ko_015_wiki_semiconductor.txt | https://ko.wikipedia.org/wiki/반도체 | Encyclopedia | technical/science |
| ko_016_wiki_coffee.txt | https://ko.wikipedia.org/wiki/커피 | Encyclopedia | food, mixed Hanja/Latin gloss in lead |
| ko_017_wiki_covid19.txt | https://ko.wikipedia.org/wiki/코로나19_범유행 | Encyclopedia | medicine |
| ko_018_blog_brunch_dog_walk.txt | https://brunch.co.kr/@hyeishrecipe/254 | Blog (Brunch essay platform) | pet-care essay/reported piece |
| ko_019_blog_tistory_chicken_best10.txt | https://sun1.greenharmony11.com/entry/... | Blog (Tistory-engine custom domain) | restaurant-recommendation listicle |
| ko_020_wiki_bts.txt | https://ko.wikipedia.org/wiki/방탄소년단 | Encyclopedia | pop culture |
| ko_021_wiki_samsung_electronics.txt | https://ko.wikipedia.org/wiki/삼성전자 | Encyclopedia | corporate/technical |
| ko_022_wiki_jangma.txt | https://ko.wikipedia.org/wiki/장마 | Encyclopedia | weather/geography, incl. Hanja term (收斂帶) |
| ko_023_wiki_goryeo.txt | https://ko.wikipedia.org/wiki/고려_시대 | Encyclopedia | history |
| ko_024_wiki_korean_literature.txt | https://ko.wikipedia.org/wiki/한국_문학 | Encyclopedia | literature/humanities |
| ko_025_wiki_hangeul.txt | https://ko.wikipedia.org/wiki/한글 | Encyclopedia | Hanja-dense (script history, 吏讀/口訣/句讀) |
| ko_026_news_eroun_ev_battery.txt | https://www.eroun.net/news/articleView.html?idxno=34295 | News (trade/industry) | EV battery technology explainer |
| ko_027_blog_heydealer_kia_battery.txt | https://www.heydealer.com/blog/... | Blog (corporate/brand blog) | automotive review |
| ko_028_wiki_jeju_island.txt | https://ko.wikipedia.org/wiki/제주도 | Encyclopedia | geography |
| ko_029_blog_tistory_home_training.txt | https://metamorphosis.kr/entry/... | Blog (Tistory-engine custom domain) | personal fitness/diet essay |
| ko_030_news_hidoc_home_workout.txt | https://news.hidoc.co.kr/news/articleView.html?idxno=24364 | News (health magazine) | workout how-to article |
| ko_031_wiki_confucianism.txt | https://ko.wikipedia.org/wiki/유교 | Encyclopedia | Hanja-dense (religion/philosophy, 儒敎/儒家/儒生) |

Source-type breakdown: 22 Wikipedia (ko.wikipedia.org) encyclopedia articles
(chosen for topic diversity and to deliberately include Hanja-dense
historical/legal/philosophical subjects per the debt entry's specific
concern), 5 news-site articles (OhmyNews, Travie, Khan, Eroun, Hidoc), and
4 blog-platform posts (Brunch, 2x Tistory-engine custom domains,
HeyDealer's brand blog).

Direct Naver Blog (`blog.naver.com`) and most `chosun.com` / `hani.co.kr`
articles could not be retrieved — those platforms render article body
content client-side (JS/iframe), which the fetch tooling used in this
session cannot execute. `namu.wiki` returned HTTP 403 to every request
(anti-bot). This is documented here rather than silently worked around.

## Negative-control corpus (`negative/`, N=7) — non-Korean text

Used only to verify the calibration doesn't introduce false positives.

| file | source | language |
|---|---|---|
| neg_001_en_wikipedia_ai.txt | https://en.wikipedia.org/wiki/Artificial_intelligence | English |
| neg_002_en_wikipedia_seoul.txt | https://en.wikipedia.org/wiki/Seoul | English |
| neg_003_ja_wikipedia_japan.txt | https://ja.wikipedia.org/wiki/日本 | Japanese |
| neg_004_ja_wikipedia_sushi.txt | https://ja.wikipedia.org/wiki/寿司 | Japanese |
| neg_005_zh_wikipedia_china.txt | https://zh.wikipedia.org/wiki/中国 | Chinese |
| neg_006_ru_short_ml_article.txt | https://ru.wikipedia.org/wiki/Машинное_обучение | Russian |
| neg_007_en_short_travel_blog.txt | https://en.wikipedia.org/wiki/Travel | English |

All 7 negative-control samples are real, independently-fetched Wikipedia
text (not hand-written filler).

## Calibration result

See `tests/linkcheck/test_ko_corpus_calibration.py` docstring for the full
finding. Summary: `_RATIO_THRESHOLD = 0.30` (unchanged) achieves 100%
detection (31/31) on the positive corpus and 0/7 false positives on the
negative-control corpus — both comfortably clear of the plan's >=95%
bar. `debt_registry.toml`'s `ko-corpus-calibration` entry was updated to
`resolved` on this basis.
