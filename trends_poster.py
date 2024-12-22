import os
import feedparser
import sqlite3
from atproto import Client
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
            trend['news_title'] = news_item.find('ht:news_item_title').text
            trend['news_url'] = news_item.find('ht:news_item_url').text
        
        trends.append(trend)
    
    return trends

def format_post_content(trend):
    """投稿内容のフォーマット"""
    if 'news_title' in trend and 'news_url' in trend:
        return f"{trend['title']}\n\n{trend['news_title']}\n{trend['news_url']}"
    return trend['title']

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
                # 投稿内容のフォーマット
                post_text = format_post_content(trend)
                
                # Blueskyに投稿
                client.send_post(text=post_text)
                
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
