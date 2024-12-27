import os
import feedparser
import sqlite3
from atproto import Client, models
from datetime import datetime
import logging
from bs4 import BeautifulSoup
import requests
from urllib.parse import urlparse
import io
from PIL import Image
import re

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

def parse_traffic_volume(traffic_str):
    """検索ボリュームの文字列を数値に変換"""
    if not traffic_str:
        return 0
    
    # '500+'のような文字列から数値部分を抽出
    match = re.match(r'(\d+)\+?', traffic_str)
    if match:
        return int(match.group(1))
    return 0

def meets_volume_threshold(traffic_str, min_volume=500):
    """検索ボリュームが閾値を満たすかチェック"""
    volume = parse_traffic_volume(traffic_str)
    return volume >= min_volume

def get_trends_data():
    """RSSフィードを取得してパース"""
    response = requests.get('https://trends.google.co.jp/trending/rss?geo=JP')
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.content, 'xml')
    items = soup.find_all('item')
    
    trends = []
    for item in items:
        # 検索ボリュームを取得
        traffic = item.find('ht:approx_traffic')
        traffic_str = traffic.text.strip() if traffic else None
        
        # 検索ボリュームが閾値未満の場合はスキップ
        if not meets_volume_threshold(traffic_str):
            logging.info(f"Skipping trend due to low volume ({traffic_str}): {item.find('title').text.strip()}")
            continue
            
        trend = {
            'title': item.find('title').text.strip()
        }
        
        # ニュース項目の取得
        news_item = item.find('ht:news_item')
        if news_item:
            news_title = news_item.find('ht:news_item_title')
            news_url = news_item.find('ht:news_item_url')
            
            if news_title and news_url:
                trend['news_title'] = news_title.text.strip()
                trend['news_url'] = news_url.text.strip()
                
                # OGP画像の取得
                ogp_image = get_ogp_image(news_url.text.strip())
                if ogp_image:
                    trend['ogp_image'] = ogp_image
                
                # ニュースソースの取得
                news_source = news_item.find('ht:news_item_source')
                if news_source:
                    trend['news_source'] = news_source.text.strip()
        
        trends.append(trend)
    
    return trends

def create_rich_text(trend):
    """リッチテキストとファセット（リンク情報）を作成"""
    text = f"{trend['title']}\n\n{trend['news_title']}\n{trend['news_url']}"
    
    # URLの開始位置を計算（バイト単位）
    url_start = len(f"{trend['title']}\n\n{trend['news_title']}\n".encode('utf-8'))
    url_end = url_start + len(trend['news_url'].encode('utf-8'))
    
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

# [remaining functions: get_ogp_image, resize_image, create_embed_card stay the same]

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
            # 記事情報（タイトルとURL）が両方存在する場合のみ処理を続行
            if ('news_title' in trend and 
                'news_url' in trend and 
                not is_already_posted(conn, trend['title'])):
                
                # リッチテキストを作成
                text, facets = create_rich_text(trend)
                
                # 投稿のベースパラメータ（言語設定を含む）
                post_params = {
                    'text': text,
                    'facets': facets,
                    'langs': ['ja']  # 日本語を指定
                }
                
                # OGP画像が存在する場合のみリンクカードを作成
                if 'ogp_image' in trend:
                    embed = create_embed_card(client, trend)
                    # リンクカード付きで投稿
                    post_params['embed'] = embed
                
                # 投稿を実行
                client.send_post(**post_params)
                
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
