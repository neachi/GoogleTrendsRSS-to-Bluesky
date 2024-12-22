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

# ロギングの設定（既存のまま）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 既存の関数はそのまま維持
# init_database, is_already_posted, mark_as_posted, get_trends_data, create_rich_text は変更なし

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
        # 画像のサイズとタイプを取得
        size, mime_type = get_image_size_and_type(trend['ogp_image'])
        
        if size:
            # 画像をBlueskyにアップロード
            with requests.get(trend['ogp_image'], timeout=5) as response:
                img_data = response.content
                upload = client.com.atproto.repo.upload_blob(img_data)
            
            # サムネイル情報を設定
            external_params['thumb'] = {
                'ref': {
                    '$link': upload.blob.ref
                },
                'mime_type': mime_type,
                'size': size
            }
    
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
                    
                    # OGP画像が存在する場合のみリンクカードを作成
                    if 'ogp_image' in trend:
                        embed = create_embed_card(client, trend)
                        # リンクカード付きで投稿
                        client.send_post(
                            text=text,
                            facets=facets,
                            embed=embed
                        )
                    else:
                        # リンクカードなしで投稿
                        client.send_post(
                            text=text,
                            facets=facets
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
