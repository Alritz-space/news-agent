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
    return hashlib.sha256((title + link).encode()).hexdigest()

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
        "%Y-%m-%dT%H:%M:%SZ",
        "%m/%d/%Y, %I:%M %p, +0000 UTC",
        "%b %d, %Y",
        "%B %d, %Y"
    ]
    for fmt in formats:
        try:
            pub_date = datetime.strptime(pub_date_str, fmt).replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - pub_date <= timedelta(hours=24)
        except ValueError:
            continue
    print(f"Could not parse publication date: {pub_date_str}")
    return False

def filter_articles_by_keywords(articles, keywords):
    if not keywords:
        return articles
    keywords_lower = [kw.lower() for kw in keywords]
    return [a for a in articles if any(kw in (a.get('title', '') + ' ' + a.get('snippet', '')).lower() for kw in keywords_lower)]

def fetch_news_serpapi(query, api_key, keywords=None):
    print(f"Trying SerpAPI for: {query}")
    query_string = f"{query} ({' OR '.join(keywords)})" if keywords else query
    params = {
        "engine": "google_news",
        "q": query_string,
        "api_key": api_key,
        "hl": "en",
        "gl": "us",
        "sort_by": "date",
        "tbs": "qdr:d",
        "num": 100
    }
    try:
        resp = requests.get("https://serpapi.com/search.json", params=params)
        if resp.status_code != 200:
            print(f"SerpAPI failed: {resp.text}")
            return []
        data = resp.json().get("news_results", [])
        return [
            {
                "title": i.get("title"),
                "link": i.get("link"),
                "snippet": i.get("snippet", ""),
                "pub_date": i.get("date"),
                "source": i.get("source")
            }
            for i in data
            if not i.get("date") or article_within_last_24_hours(i.get("date"))
        ][:5]
    except Exception as e:
        print(f"SerpAPI exception: {e}")
        return []

def fetch_news_googleapi(query, google_api_key, cse_id, keywords=None):
    print(f"Trying Google Custom Search API for: {query}")
    query_string = f"{query} {' '.join(keywords)}" if keywords else query
    params = {
        "key": google_api_key,
        "cx": cse_id,
        "q": query_string,
        "sort": "date"
    }
    try:
        resp = requests.get("https://www.googleapis.com/customsearch/v1", params=params)
        if resp.status_code != 200:
            print(f"Google API failed: {resp.text}")
            return []
        items = resp.json().get("items", [])
        return [
            {
                "title": i.get("title"),
                "link": i.get("link"),
                "snippet": i.get("snippet", ""),
                "pub_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": i.get("displayLink", "")
            }
            for i in items
        ][:5]
    except Exception as e:
        print(f"Google API exception: {e}")
        return []

def summarize_article(article):
    snippet = article.get('snippet', '')
    summary = snippet[:120] + ('...' if len(snippet) > 120 else '')
    return f"{article.get('title', 'No Title')} - {summary}"

def compose_email(news):
    html = f"<h2>Daily News Summary - {datetime.utcnow().strftime('%Y-%m-%d')}</h2>"
    for org, articles in news.items():
        html += f"<h3>{org}</h3><ul>"
        for a in articles:
            summary = summarize_article(a)
            html += f"<li><a href='{a.get('link', '#')}'>{summary}</a> ({a.get('pub_date', 'N/A')}) - <i>{a.get('source', 'N/A')}</i></li>"
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
    orgs = load_organizations()
    filters = load_filters()
    if not orgs:
        print("No organizations to process.")
        return

    # Load secrets from GitHub Actions environment
    to_email = os.getenv("EMAIL_TO")
    from_email = os.getenv("EMAIL_FROM")
    from_pass = os.getenv("EMAIL_PASS")
    serpapi_key = os.getenv("SERPAPI_KEY")
    google_key = os.getenv("GOOGLE_API_KEY")
    google_cse_id = os.getenv("GOOGLE_CSE_ID")

    if not all([to_email, from_email, from_pass, serpapi_key, google_key, google_cse_id]):
        print("Missing environment variables.")
        return

    stored_hashes = load_stored_hashes()
    new_news = {}

    for org in orgs:
        keywords = filters.get(org, None)
        articles = fetch_news_serpapi(org, serpapi_key, keywords)
        if not articles:
            articles = fetch_news_googleapi(org, google_key, google_cse_id, keywords)
        if keywords:
            articles = filter_articles_by_keywords(articles, keywords)

        fresh_articles = []
        for art in articles:
            h = news_hash(art)
            if not stored_hashes.get(h):
                fresh_articles.append(art)
                stored_hashes[h] = True

        if fresh_articles:
            new_news[org] = fresh_articles

    if new_news:
        html_body = compose_email(new_news)
        send_email("Daily News Summary", html_body, to_email, from_email, from_pass)
    else:
        print("No new articles found.")

    save_stored_hashes(stored_hashes)

if __name__ == "__main__":
    main()
