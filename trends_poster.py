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

def get_ogp_image(url):
    """URLからOGP画像を取得"""
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # OGP画像の取得を試みる
        og_image = (
            soup.find('meta', property='og:image') or 
            soup.find('meta', property='og:image:secure_url') or
            soup.find('meta', property='twitter:image')
        )
        
        if og_image and og_image.get('content'):
            # 画像URLが存在することを確認
            img_url = og_image['content']
            img_response = requests.head(img_url, timeout=5)
            if img_response.status_code == 200:
                return img_url
    except Exception as e:
        logging.warning(f"Failed to get OGP image from {url}: {e}")
    
    return None

def get_trends_data():
    """RSSフィードを取得してパース"""
    response = requests.get('https://trends.google.co.jp/trending/rss?geo=JP')
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.content, 'xml')
    items = soup.find_all('item')
    
    trends = []
    for item in items:
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

def get_image_size_and_type(image_url):
    """画像のサイズとタイプを取得"""
    try:
        response = requests.get(image_url, timeout=5)
        response.raise_for_status()
        
        # 画像データを取得
        img_data = response.content
        
        # Blueskyに画像をアップロード
        return len(img_data), response.headers.get('content-type', 'image/jpeg')
    except Exception as e:
        logging.warning(f"Failed to get image size: {e}")
        return None, None

def create_embed_card(client, trend):
    """リンクカードの作成（OGP画像対応）"""
    external_params = {
        'uri': trend['news_url'],
        'title': trend['news_title'],
        'description': f"Source: {trend.get('news_source', 'News')}"
    }
    
    # OGP画像が存在する場合
    if 'ogp_image' in trend:
        try:
            # 画像のサイズとタイプを取得
            size, mime_type = get_image_size_and_type(trend['ogp_image'])
            
            if size:
                # 画像をBlueskyにアップロード
                with requests.get(trend['ogp_image'], timeout=5) as response:
                    img_data = response.content
                    upload = client.com.atproto.repo.upload_blob(img_data)
                
                # サムネイル情報を設定
                external_params['thumb'] = {
                    'ref': upload.blob.ref,  # 直接refを使用
                    'mimeType': mime_type,   # キャメルケースに修正
                    'size': size
                }
        except Exception as e:
            logging.warning(f"Failed to process image: {e}")
            # 画像処理に失敗した場合は画像なしで続行
    
    return models.AppBskyEmbedExternal.Main(
        external=models.AppBskyEmbedExternal.External(**external_params)
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
                else:
                    # ニュース記事がない場合はシンプルに投稿（言語設定付き）
                    client.send_post(
                        text=trend['title'],
                        langs=['ja']
                    )
                
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
