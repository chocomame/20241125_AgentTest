from urllib.parse import urljoin, urlparse, unquote, parse_qs
import re

def normalize_url(url):
    """URLを正規化（末尾のスラッシュを統一）"""
    # URLデコード（日本語などを読める形式に）
    decoded_url = unquote(url, encoding='utf-8')
    
    # index.htmlを含むURLをルートURLに正規化
    if decoded_url.lower().endswith('/index.html'):
        decoded_url = decoded_url[:-10]  # '/index.html'の長さ(10)を削除
    elif decoded_url.lower().endswith('index.html'):
        decoded_url = decoded_url[:-9]  # 'index.html'の長さ(9)を削除
    
    # .htmlで終わるURLの場合は、末尾のスラッシュを削除
    if decoded_url.lower().endswith('.html'):
        return decoded_url
    # それ以外の場合は、末尾にスラッシュを追加
    elif not decoded_url.endswith('/'):
        return decoded_url + '/'
    return decoded_url

def is_same_domain(url, base_domain):
    """URLが同じドメインかどうかをチェック"""
    return urlparse(url).netloc == base_domain

def is_anchor_link(url):
    """アンカーリンクかどうかをェック"""
    return '#' in url

def contains_japanese(text):
    """テキストに日本語が含まれているかチェック"""
    japanese_pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')
    return bool(japanese_pattern.search(text))

def is_preview_url(url):
    """プレビューURLかどうかをチェック"""
    preview_params = ['preview', 'preview_id', 'preview_nonce', '_thumbnail_id']
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    
    # プレビュー関連のパラメータが含まれているかチェック
    return any(param in query_params for param in preview_params)

def get_all_links(url, base_domain, soup):
    """ページ内の全リンクを取得"""
    try:
        links = set()
        # aタグとフレームタグの両方からリンクを取得
        for element in soup.find_all(['a', 'frame', 'iframe']):
            href = element.get('href') or element.get('src')
            if href:
                # 相対パスを絶対パスに変換
                absolute_url = urljoin(url, href)
                parsed_url = urlparse(absolute_url)
                
                # index.htmlで終わるURLは除外（ルートURLと同じため）
                if parsed_url.path.lower().endswith('index.html'):
                    continue
                
                # 同じドメインのURLのみを対象とする
                if (parsed_url.netloc == base_domain and
                    not is_anchor_link(absolute_url) and
                    not absolute_url.lower().endswith('.pdf') and
                    not is_preview_url(absolute_url)):
                    
                    # URLを正規化（末尾のスラッシュを削除）
                    normalized_url = absolute_url.rstrip('/')
                    
                    # .htmlで終わるURLの場合はそのまま追加
                    if normalized_url.lower().endswith('.html'):
                        links.add(normalized_url)
                    # .htmlで終わらないURLの場合は、末尾のスラッシュを追加
                    else:
                        links.add(normalized_url + '/')
        
        return links
    except Exception:
        return set() 