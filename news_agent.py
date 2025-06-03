import requests
import json
import time
from datetime import date

# CONFIGURATION
SERPAPI_KEY = '12959484f638446e313ea45e2c637f3a48c401096221580185c4075cba928d2b'  # Get this from https://serpapi.com/
SEARCH_ENGINE = 'google'  # or 'bing' if you want
RESULTS_FILE = 'seen_articles.json'
ORG_FILE = 'orgs.txt'

def load_orgs():
    with open(ORG_FILE, 'r') as f:
        return [line.strip() for line in f if line.strip()]

def load_seen_articles():
    try:
        with open(RESULTS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_seen_articles(seen):
    with open(RESULTS_FILE, 'w') as f:
        json.dump(seen, f, indent=2)

def search_news(org, api_key):
    params = {
        'engine': 'google_news',
        'q': org,
        'api_key': api_key
    }
    resp = requests.get('https://serpapi.com/search', params=params)
    data = resp.json()
    return data.get('news_results', [])

def main():
    orgs = load_orgs()
    seen_articles = load_seen_articles()
    new_articles = {}

    for org in orgs:
        print(f"Searching news for {org}...")
        articles = search_news(org, SERPAPI_KEY)
        seen_org = seen_articles.get(org, [])

        new_for_org = []
        for article in articles:
            link = article.get('link')
            if link and link not in seen_org:
                new_for_org.append(article)
                seen_org.append(link)

        if new_for_org:
            new_articles[org] = new_for_org
        seen_articles[org] = seen_org
        time.sleep(1)  # Be polite with API rate limits

    save_seen_articles(seen_articles)

    # Output result
    today = str(date.today())
    print(f"\n📰 News Summary for {today}:")
    if not new_articles:
        print("No new articles found.")
    else:
        for org, articles in new_articles.items():
            print(f"\n🔎 {org}:")
            for art in articles:
                print(f" - {art.get('title')}\n   {art.get('link')}")

if __name__ == '__main__':
    main()
