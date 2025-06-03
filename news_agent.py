import os
import json
import smtplib
import hashlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests

DATA_FILE = 'seen_articles.json'
ORG_FILE = 'orgs.txt'

def load_stored_hashes():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_stored_hashes(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def news_hash(item):
    # Defensive handling of missing fields
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

def fetch_news_serpapi(query, api_key):
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_news",
        "q": query,
        "api_key": api_key,
        "hl": "en",
        "gl": "us",
        "sort_by": "date",
        "num": 10
    }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"Failed to fetch news for {query}: {response.text}")
        return []
    data = response.json()
    news_results = data.get("news_results", [])
    articles = []
    for item in news_results:
        title = item.get("title")
        link = item.get("link")
        if not title or not link:
            continue  # Skip incomplete articles
        articles.append({
            "title": title,
            "link": link,
            "pub_date": item.get("date")
        })
    return articles

def compose_email(new_news):
    html = f"<h2>Daily News Summary - {datetime.utcnow().strftime('%Y-%m-%d')}</h2>"
    for org, articles in new_news.items():
        html += f"<h3>{org}</h3><ul>"
        for art in articles:
            html += f"<li><a href='{art['link']}'>{art['title']}</a> ({art['pub_date']})</li>"
        html += "</ul>"
    return html

def send_email(subject, html_body, to_email, from_email, from_pass):
    msg = MIMEMultipart('alternative')
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html'))

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(from_email, from_pass)
    server.send_message(msg)
    server.quit()

def main():
    org_list = load_organizations()
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
        articles = fetch_news_serpapi(org, serpapi_key)
        fresh_articles = []
        for art in articles:
            if not art.get("title") or not art.get("link"):
                print("Skipping article due to missing title or link:", art)
                continue
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
