import os
import json
import smtplib
import hashlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
import requests

DATA_FILE = 'seen_articles.json'
ORG_FILE = 'orgs.txt'
FILTERS_FILE = 'filters.json'

def load_stored_hashes():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_stored_hashes(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def news_hash(item):
    title = item.get('title') or ''
    link = item.get('link') or ''
    unique_str = title + link
    return hashlib.sha256(unique_str.encode()).hexdigest()

def load_organizations():
    if not os.path.exists(ORG_FILE):
        print(f"Missing {ORG_FILE}")
        return []
    with open(ORG_FILE, 'r') as f:
        return [line.strip() for line in f if line.strip()]

def load_filters():
    if not os.path.exists(FILTERS_FILE):
        print(f"Missing {FILTERS_FILE}, continuing without context filters.")
        return {}
    with open(FILTERS_FILE, 'r') as f:
        return json.load(f)

def article_within_last_24_hours(pub_date_str):
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",              # ISO format
        "%m/%d/%Y, %I:%M %p, +0000 UTC",   # e.g., 02/04/2025, 08:00 AM, +0000 UTC
        "%b %d, %Y",                       # e.g., Apr 30, 2025
        "%B %d, %Y"                        # e.g., April 30, 2025
    ]
    for fmt in formats:
        try:
            pub_date = datetime.strptime(pub_date_str, fmt).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return now - pub_date <= timedelta(hours=24)
        except ValueError:
            continue
    print(f"Could not parse publication date: {pub_date_str}")
    return False

def filter_articles_by_keywords(articles, keywords):
    if not keywords:
        return articles
    filtered = []
    keywords_lower = [k.lower() for k in keywords]
    for art in articles:
        content = (art.get('title', '') + ' ' + art.get('snippet', '')).lower()
        if any(kw in content for kw in keywords_lower):
            filtered.append(art)
    return filtered

def fetch_news_serpapi(org, api_key, keywords=None):
    url = "https://serpapi.com/search.json"
    query = f"{org} ({' OR '.join(keywords)})" if keywords else org

    params = {
        "engine": "google_news",
        "q": query,
        "api_key": api_key,
        "hl": "en",
        "gl": "us",
        "sort_by": "date",
        "tbs": "qdr:d",     # Last 24 hours
        "num": 100,
        "no_cache": True    # Forces fresh results (optional, remove if rate limits are a concern)
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"Failed to fetch news for {org}: {response.text}")
        return []

    data = response.json()
    news_results = data.get("news_results", [])
    articles = []
    for item in news_results:
        title = item.get("title")
        link = item.get("link")
        snippet = item.get("snippet", "")
        pub_date = item.get("date")
        source = item.get("source", "")

        # Best-effort parse of date (SerpAPI formats can vary)
        if pub_date and not article_within_last_24_hours(pub_date):
            continue

        article = {
            "title": title,
            "link": link,
            "snippet": snippet,
            "pub_date": pub_date,
            "source": source
        }
        articles.append(article)

    return articles[:5]

def summarize_article(article):
    snippet = article.get('snippet', '')
    summary = snippet[:120] + ('...' if len(snippet) > 120 else '')
    return f"{article.get('title', 'No Title')} - {summary}"

def compose_email(new_news):
    html = f"<h2>Daily News Summary - {datetime.utcnow().strftime('%Y-%m-%d')}</h2>"
    for org, articles in new_news.items():
        html += f"<h3>{org}</h3><ul>"
        for art in articles:
            summary = summarize_article(art)
            html += f"<li><a href='{art.get('link','#')}'>{summary}</a> ({art.get('pub_date', 'N/A')}) - <i>{art.get('source', 'N/A')}</i></li>"
        html += "</ul>"
    return html

def send_email(subject, html_body, to_email, from_email, from_pass):
    msg = MIMEMultipart('alternative')
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(from_email, from_pass)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Error sending email: {e}")

def main():
    org_list = load_organizations()
    filters = load_filters()
    if not org_list:
        print("No organizations found in orgs.txt.")
        return

    to_email = os.getenv('EMAIL_TO')
    from_email = os.getenv('EMAIL_FROM')
    from_pass = os.getenv('EMAIL_PASS')
    serpapi_key = os.getenv('SERPAPI_KEY')

    if not all([to_email, from_email, from_pass, serpapi_key]):
        print("Missing environment variables for email or SerpAPI key.")
        return

    stored_hashes = load_stored_hashes()
    new_news = {}

    for org in org_list:
        print(f"Fetching news for {org}...")
        keywords = filters.get(org, None)
        articles = fetch_news_serpapi(org, serpapi_key, keywords)
        fresh_articles = []
        for art in articles:
            h = news_hash(art)
            if stored_hashes.get(h):
                continue
            fresh_articles.append(art)
            stored_hashes[h] = True

        if fresh_articles:
            new_news[org] = fresh_articles

    if new_news:
        print(f"Sending email for {len(new_news)} organizations.")
        html_body = compose_email(new_news)
        send_email(
            subject="Daily News Summary",
            html_body=html_body,
            to_email=to_email,
            from_email=from_email,
            from_pass=from_pass
        )
    else:
        print("No new news found today.")

    save_stored_hashes(stored_hashes)

if __name__ == "__main__":
    main()
