import os
import feedparser
import sqlite3
from atproto import Client, models
from datetime import datetime
import logging
from bs4 import BeautifulSoup
import requests

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def init_database():
    """データベースの初期化"""
    conn = sqlite3.connect('trends.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS posted_trends
        (trend_title TEXT PRIMARY KEY, posted_at TIMESTAMP)
    ''')
    conn.commit()
    return conn

def is_already_posted(conn, trend_title):
    """トレンドが既に投稿済みかチェック"""
    c = conn.cursor()
    c.execute('SELECT 1 FROM posted_trends WHERE trend_title = ?', (trend_title,))
    return c.fetchone() is not None

def mark_as_posted(conn, trend_title):
    """トレンドを投稿済みとしてマーク"""
    c = conn.cursor()
    c.execute(
        'INSERT INTO posted_trends (trend_title, posted_at) VALUES (?, ?)',
        (trend_title, datetime.now())
    )
    conn.commit()

def get_trends_data():
    """RSSフィードを取得してパース"""
    response = requests.get('https://trends.google.co.jp/trending/rss?geo=JP')
    soup = BeautifulSoup(response.content, 'xml')
    items = soup.find_all('item')
    
    trends = []
    for item in items:
        trend = {
            'title': item.find('title').text
        }
        
        # ニュース項目の取得
        news_item = item.find('ht:news_item')
        if news_item:
            news_title = news_item.find('ht:news_item_title')
            news_url = news_item.find('ht:news_item_url')
            if news_title and news_url:
                trend['news_title'] = news_title.text
                trend['news_url'] = news_url.text
                # ニュースソースの取得
                news_source = news_item.find('ht:news_item_source')
                if news_source:
                    trend['news_source'] = news_source.text
        
        trends.append(trend)
    
    return trends

def create_rich_text(trend):
    """リッチテキストとファセット（リンク情報）を作成"""
    text = f"{trend['title']}\n\n{trend['news_title']}\n{trend['news_url']}"
    
    # URLの開始位置を計算
    url_start = len(f"{trend['title']}\n\n{trend['news_title']}\n")
    url_end = url_start + len(trend['news_url'])
    
    # ファセットの作成（リンク情報）
    facets = [
        models.AppBskyRichtextFacet.Main(
            features=[
                models.AppBskyRichtextFacet.Link(uri=trend['news_url'])
            ],
            index=models.AppBskyRichtextFacet.ByteSlice(
                byteStart=url_start,
                byteEnd=url_end
            )
        )
    ]
    
    return text, facets

def create_embed_card(trend):
    """リンクカードの作成"""
    return models.AppBskyEmbedExternal.Main(
        external=models.AppBskyEmbedExternal.External(
            title=trend['news_title'],
            description=f"Source: {trend.get('news_source', 'News')}",
            uri=trend['news_url']
        )
    )

def main():
    # Blueskyクレデンシャルの取得
    username = os.environ['BLUESKY_USERNAME']
    password = os.environ['BLUESKY_PASSWORD']

    # Blueskyクライアントの初期化
    client = Client()
    client.login(username, password)

    # データベース接続
    conn = init_database()

    try:
        # トレンドデータの取得
        trends = get_trends_data()
        
        for trend in trends:
            if not is_already_posted(conn, trend['title']):
                if 'news_title' in trend and 'news_url' in trend:
                    # リッチテキストとリンクカードを作成
                    text, facets = create_rich_text(trend)
                    embed = create_embed_card(trend)
                    
                    # 投稿を作成
                    client.send_post(
                        text=text,
                        facets=facets,
                        embed=embed
                    )
                else:
                    # ニュース記事がない場合はシンプルに投稿
                    client.send_post(text=trend['title'])
                
                # 投稿済みとしてマーク
                mark_as_posted(conn, trend['title'])
                logging.info(f"Posted new trend: {trend['title']}")

    except Exception as e:
        logging.error(f"Error occurred: {e}")
        raise e

    finally:
        conn.close()

if __name__ == "__main__":
    main()
