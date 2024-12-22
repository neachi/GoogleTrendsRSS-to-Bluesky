import os
import feedparser
import sqlite3
from atproto import Client
from datetime import datetime
import logging
from xml.etree import ElementTree as ET

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

def format_post_content(entry):
    """エントリーから投稿内容を生成"""
    title = entry.title
    
    # ht:news_item タグを探す
    news_items = entry.get('ht_news_item', [])
    
    if not news_items:  # 関連記事がない場合
        return title
    
    # 最初の関連記事の情報を取得
    first_news = news_items[0]
    news_title = first_news.get('ht_news_item_title', '')
    news_url = first_news.get('ht_news_item_url', '')
    
    # 関連記事の情報がある場合
    if news_title and news_url:
        return f"{title}\n{news_title}\n{news_url}"
    
    # 関連記事の情報が不完全な場合
    return title

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
        # Google TrendsのRSSフィードを取得
        feed = feedparser.parse('https://trends.google.co.jp/trending/rss?geo=JP')
        
        for entry in feed.entries:
            if not is_already_posted(conn, entry.title):
                # 投稿内容のフォーマット
                post_text = format_post_content(entry)
                
                # Blueskyに投稿
                client.send_post(text=post_text)
                
                # 投稿済みとしてマーク
                mark_as_posted(conn, entry.title)
                logging.info(f"Posted new trend: {entry.title}")

    except Exception as e:
        logging.error(f"Error occurred: {e}")
        raise e

    finally:
        conn.close()

if __name__ == "__main__":
    main()
