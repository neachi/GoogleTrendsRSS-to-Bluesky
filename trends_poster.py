import os
import requests
import feedparser
from atproto import Client, models
from datetime import datetime
from urllib.parse import urlparse

# 環境変数
BSKY_USERNAME = os.getenv("BSKY_USERNAME")
BSKY_PASSWORD = os.getenv("BSKY_PASSWORD")
GOOGLE_TRENDS_RSS = os.getenv("GOOGLE_TRENDS_RSS")

# RSSフィードの取得
def fetch_rss_feed(feed_url):
    return feedparser.parse(feed_url)

# 画像URLのバリデーション
def validate_image_url(url):
    try:
        response = requests.head(url)
        content_type = response.headers.get("Content-Type", "")
        return response.status_code == 200 and content_type.startswith("image/")
    except Exception:
        return False

# トレンドデータの作成
def parse_trends(feed):
    trends = []
    for entry in feed.entries:
        trend = {
            "title": entry.title,
            "url": entry.link,
            "news_title": entry.get("ht_news_item_title", ""),
            "news_url": entry.get("ht_news_item_url", ""),
            "news_source": entry.get("ht_news_item_source", ""),
            "news_picture": entry.get("ht_news_item_picture", "")
        }
        trends.append(trend)
    return trends

# Bluesky投稿の作成
def create_post_text(trend):
    post_text = f"{trend['title']}\n\n"
    if trend['news_title'] and trend['news_url']:
        post_text += f"{trend['news_title']}\n{trend['news_url']}\n\n"
    return post_text.strip()

# リンクカードの作成
def create_embed_card(trend):
    """リンクカードの作成（画像対応）"""
    external_params = {
        'title': trend['news_title'],
        'description': f"Source: {trend.get('news_source', 'News')}",
        'uri': trend['news_url']
    }
    
    # 画像URLが存在する場合は追加
    if trend['news_picture'] and validate_image_url(trend['news_picture']):
        external_params['thumb'] = trend['news_picture']
    
    return models.AppBskyEmbedExternal.Main(
        external=models.AppBskyEmbedExternal.External(**external_params)
    )

# トレンド投稿の処理
def post_trends_to_bluesky(client, trends):
    for trend in trends:
        post_text = create_post_text(trend)
        
        embed = None
        if trend['news_title'] and trend['news_url']:
            embed = create_embed_card(trend)
        
        try:
            client.com.atproto.repo.create_record(
                models.ComAtprotoRepoCreateRecord.Data(
                    repo=client.me.did,
                    collection="app.bsky.feed.post",
                    record=models.AppBskyFeedPost.Main(
                        text=post_text,
                        createdAt=datetime.utcnow().isoformat(),
                        embed=embed
                    )
                )
            )
            print(f"Posted: {post_text[:30]}...")
        except Exception as e:
            print(f"Failed to post trend: {trend['title']} - Error: {e}")

# メイン処理
def main():
    # RSSフィードの取得
    feed = fetch_rss_feed(GOOGLE_TRENDS_RSS)
    trends = parse_trends(feed)
    
    if not trends:
        print("No trends found.")
        return

    # Blueskyにログイン
    client = Client()
    client.login(BSKY_USERNAME, BSKY_PASSWORD)

    # トレンドを投稿
    try:
        post_trends_to_bluesky(client, trends)
    except Exception as e:
        print(f"Error occurred: {e}")
        raise e

if __name__ == "__main__":
    main()
