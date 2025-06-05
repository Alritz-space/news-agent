# ... keep all your current imports
import os
import json
import smtplib
import hashlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
import requests

# (keep all your helper functions: load_stored_hashes, save_stored_hashes, news_hash, etc.)

def fetch_news_google_cse(org, api_key, cse_id, keywords=None):
    query = f"{org} {' '.join(keywords)}" if keywords else org
    params = {
        "key": api_key,
        "cx": cse_id,
        "q": query,
        "sort": "date",  # Sort by date if supported by your CSE config
        "num": 10
    }
    response = requests.get("https://www.googleapis.com/customsearch/v1", params=params)
    if response.status_code != 200:
        print(f"Google CSE failed for {org}: {response.text}")
        return []

    data = response.json()
    articles = []
    for item in data.get("items", []):
        article = {
            "title": item.get("title"),
            "link": item.get("link"),
            "snippet": item.get("snippet", ""),
            "pub_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),  # fallback: assume now
            "source": item.get("displayLink", "Google")
        }
        articles.append(article)
    return articles[:5]

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
    google_api_key = os.getenv('GOOGLE_API_KEY')
    google_cse_id = os.getenv('GOOGLE_CSE_ID')

    if not all([to_email, from_email, from_pass, serpapi_key, google_api_key, google_cse_id]):
        print("Missing one or more required environment variables.")
        return

    stored_hashes = load_stored_hashes()
    new_news = {}

    for org in org_list:
        print(f"Fetching news for {org}...")
        keywords = filters.get(org, None)

        articles = fetch_news_serpapi(org, serpapi_key, keywords)

        if not articles:
            print(f"No SerpAPI results for {org}, trying Google CSE...")
            articles = fetch_news_google_cse(org, google_api_key, google_cse_id, keywords)

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
