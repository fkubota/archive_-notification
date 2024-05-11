import feedparser

rss_url = "https://www.cambridge.org/core/rss/product/id/F8F44ED0833DA6BE0A78F7639898FA08"
d = feedparser.parse(rss_url)
print(d)