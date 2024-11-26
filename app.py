import streamlit as st
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
from urllib.parse import urljoin, urlparse, unquote, parse_qs
import pandas as pd
import re
from html.parser import HTMLParser

class HTMLSyntaxChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors = []
        self.open_tags = []
        self.line_number = 1
        self.column = 0

    def handle_starttag(self, tag, attrs):
        self.open_tags.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if self.open_tags:
            if self.open_tags[-1][0] == tag:
                self.open_tags.pop()
            else:
                pos = self.getpos()
                self.errors.append(f"タグの閉じ忘れ: 行 {pos[0]}, 列 {pos[1]} - {tag}タグが正しく閉じられていません")

    def handle_data(self, data):
        self.line_number += data.count('\n')

def check_html_syntax(html_content):
    """HTMLの閉じタグをチェック"""
    syntax_errors = []
    
    # PHPコードと特殊文字を一時的プレースホルダー置換
    replacements = []
    
    def replace_special_content(content):
        # PHPコードを置換
        content = re.sub(r'<\?php.*?\?>', 
                        lambda match: f"PLACEHOLDER_{len(replacements)}",
                        content, flags=re.DOTALL)
        
        # 特殊文字エンティティを置換
        content = re.sub(r'&[a-zA-Z]+;',
                        lambda match: f"PLACEHOLDER_{len(replacements)}",
                        content)
        
        return content
    
    # コンテンツを前処理
    processed_content = replace_special_content(html_content)
    
    # HTMLをパース
    soup = BeautifulSoup(processed_content, 'html.parser')
    
    # 重要なタグのリスト（チェックしたいタグを指定）
    important_tags = ['div', 'p', 'section', 'article', 'main', 'header', 'footer', 'nav', 'aside']
    
    # 行番号を取得するための準備
    lines = processed_content.split('\n')
    original_lines = html_content.split('\n')
    
    for tag_name in important_tags:
        # タグの開始位置を全て取得
        tag_pattern = re.compile(f'<{tag_name}[^>]*>')
        start_positions = [(i + 1, m.start()) for i, line in enumerate(lines) 
                          for m in re.finditer(tag_pattern, line)]
        
        # タグの終了位置を全て取得
        end_pattern = re.compile(f'</{tag_name}>')
        end_positions = [(i + 1, m.start()) for i, line in enumerate(lines) 
                        for m in re.finditer(end_pattern, line)]
        
        # 開始タグと終了タグの数を比較
        if len(start_positions) > len(end_positions):
            # 閉じられていないタグの位置を特定
            unclosed_tags = []
            for i, (line_num, pos) in enumerate(start_positions):
                # 対応する終了タグがない場合
                if i >= len(end_positions):
                    # 元のコンテキストを取得
                    original_line = original_lines[line_num - 1]
                    context_start = max(0, pos - 25)
                    context_end = min(len(original_line), pos + 25)
                    context = original_line[context_start:context_end]
                    
                    # 明らかな誤検出を除外
                    if not any(ignore in context for ignore in [
                        '<?php',
                        '?>',
                        '<!--',
                        '-->',
                        '[',
                        ']',
                        '&copy;'  # 特殊文字エンティティを除外
                    ]):
                        # 行全体を確認して閉じタグが存在するかチェック
                        full_line = original_line
                        if f'</{tag_name}>' in full_line:
                            continue  # 同じ行に閉じタグがある場合はスキップ
                        
                        unclosed_tags.append(f"行 {line_num}: {context}")
            
            if unclosed_tags:
                syntax_errors.append(f"警告: {tag_name}タグの閉じ忘れが{len(unclosed_tags)}個あります:")
                for location in unclosed_tags:
                    syntax_errors.append(f"  → {location}")
    
    return syntax_errors

def is_same_domain(url, base_domain):
    """URLが同じドメインかどうかをチェック"""
    return urlparse(url).netloc == base_domain

def is_anchor_link(url):
    """アンカーリンクかどうかをチェック"""
    return '#' in url

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

def contains_japanese(text):
    """テキストに日本語が含まれているかチェック"""
    japanese_pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')
    return bool(japanese_pattern.search(text))

def check_heading_order(soup):
    """見出しタグの順序と英語のみの見出しをチェック"""
    headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    heading_issues = []
    english_only_headings = []
    prev_level = 0
    
    for i, heading in enumerate(headings, 1):
        current_level = int(heading.name[1])
        heading_text = heading.get_text().strip()
        
        # 見出しレベルのチェック
        if prev_level > 0:
            # 見出しレベルが2以上飛んでいる場合のみチェック
            # h2→h4, h3→h5 などの飛びを検出
            if current_level - prev_level > 1 and current_level > prev_level:
                heading_issues.append(
                    f"h{prev_level}からh{current_level}に飛んでいます（{heading_text}）"
                )
        elif current_level != 1 and i == 1:
            # 最初の見出しがh1でない場合
            heading_issues.append(
                f"最初の見出しがh1ではなくh{current_level}です（{heading_text}）"
            )
        
        # 英語のみのチェック
        if heading_text and not contains_japanese(heading_text):
            # 数字とアルファベットのみで構成されているかチェック
            if re.match(r'^[a-zA-Z0-9\s\-_.,!?]*$', heading_text):
                english_only_headings.append(f"{heading.name}: {heading_text}")
        
        prev_level = current_level
    
    # 問題を連番で整形
    formatted_issues = []
    for i, issue in enumerate(heading_issues, 1):
        formatted_issues.append(f"{i}: {issue}")
    
    return formatted_issues, english_only_headings

def check_image_alt(soup, url):
    """画像のalt属性をチェック"""
    # /blog/または/category/を含むURLの場合はチェックをスキップ
    if '/blog/' in url or '/category/' in url:
        return 'skip'
        
    images_without_alt = []
    total_images = 0
    
    # すべてのimg要素を検索
    all_images = soup.find_all('img')
    
    for img in all_images:
        src = None
        # src属性の確認
        if img.get('src'):
            src = img.get('src')
        # srcset属性の確認
        elif img.get('srcset'):
            srcset = img.get('srcset')
            # 最初の画像URLを取得
            src = srcset.split(',')[0].strip().split(' ')[0]
            
        if src:
            # 相対URLを絶対URLに変換
            if not src.startswith(('http://', 'https://')):
                src = urljoin(url, src)
            
            # データURLやbase64エンコードされた画像、PDFファイルは除外
            if not src.startswith('data:') and not src.lower().endswith('.pdf'):
                total_images += 1
                alt = img.get('alt', '').strip()
                if not alt:
                    if src not in images_without_alt:
                        images_without_alt.append(src)
    
    # 結果を返す
    if total_images == 0:
        return '- 画像なし'
    elif images_without_alt:
        # URLをHTML形式のリンクに変換し、改行をbrタグに変換
        linked_urls = [f'<span class="image-url">{i+1}: <a href="{img_url}" target="_blank">{img_url}</a></span>' 
                      for i, img_url in enumerate(images_without_alt)]
        return f'❌ alt属性なし:<br>' + ''.join(linked_urls)
    else:
        return '✅ OK'

def check_keyword_repetition(text):
    """テキスト内のキーワード重複をチェック"""
    if not text:
        return []
    
    # 特定のストップワード（無視する単語）を定義
    stop_words = {'の', 'や', 'が', 'を', 'に', 'へ', 'で', 'から', 'まで', 'より', 'も', 'は', '・', '|', '-'}
    
    # 許療科関連の用語（これらは重複をカウントしない）
    medical_specialties = {
        # 基本診療科
        '内科', '外科', '眼科', '歯科', '耳鼻科', '皮膚科', '小児科',
        '整形外科', '産婦人科', '泌尿器科', '精神科', '脳神経外科',
        '放射線科', '麻酔科', '形成外科', '救急科',
        
        # 歯科の専門分野
        '小児歯科', '矯正歯科', '審美歯科', '口腔外科', '歯科口腔外科',
        '予防歯科', '保存歯科', '補綴歯科', 'インプラント', '一般歯科',
        
        # 内科の専門分野
        '消化器内科', '循環器内科', '呼吸器内科', '脳神経内科',
        '血液内科', '腎臓内科', '糖尿病内科', 'アレルギー科',
        
        # その他の専門分野
        '消化器外科', '心臓血管外科', '呼吸器外科', '脳神経外科',
        '小児外科', '乳腺外科', '気管食道科',
        
        # 医療機関を表す一般的な用語
        '病院', 'クリニック', '医院', '診療所'
    }
    
    # テキストを分かち書きして単語に分割
    words = []
    temp_words = re.findall(r'[一-龯ぁ-んァ-ンa-zA-Z0-9]+', text)
    
    # 複合語を優先的に検出
    i = 0
    while i < len(temp_words):
        # 3単語の組み合わせをチェック
        if i + 2 < len(temp_words):
            triple = temp_words[i] + temp_words[i + 1] + temp_words[i + 2]
            if triple in medical_specialties:
                words.append(triple)
                i += 3
                continue
        
        # 2単語の組み合わせをチェック
        if i + 1 < len(temp_words):
            double = temp_words[i] + temp_words[i + 1]
            if double in medical_specialties:
                words.append(double)
                i += 2
                continue
        
        # 単語が2文字以上で、ストップワードでない場合のみ追加
        if len(temp_words[i]) >= 2 and temp_words[i] not in stop_words:
            # 診療科関連の用語かチェック
            if temp_words[i] in medical_specialties:
                words.append(temp_words[i])
            else:
                # 診療科以外の単語のみカウント対象とする
                words.append(temp_words[i])
        i += 1
    
    # 各単語の出現回数をカウント（診療科関連の用語は除外）
    word_count = {}
    for word in words:
        if word not in medical_specialties:  # 診療科関連の用語は完全に除外
            word_count[word] = word_count.get(word, 0) + 1
    
    # 3回以上出現する単語をリストアップ
    repeated_words = [f"'{word}' ({count}回)" for word, count in word_count.items() if count >= 3]
    
    return repeated_words

def get_page_info(url):
    """ページのタイトルとディスクリプションを取得"""
    try:
        # プレビューURLの場合はスキップ
        if is_preview_url(url):
            return {
                'url': normalize_url(url),
                'title': "スキップ（プレビューURL）",
                'description': "スキップ（プレビューURL）",
                'title_length': 0,
                'description_length': 0,
                'title_status': '- スキップ',
                'description_status': '- スキップ',
                'heading_issues': '- スキップ',
                'english_only_headings': '- スキップ',
                'images_without_alt': '- スキップ',
                'html_syntax': '- スキップ'
            }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        # エンコーディングの自動検出と設定
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding
        
        # 404エラーの場合は結果に含めない
        if response.status_code == 404:
            return None
        
        response.raise_for_status()
        html_content = response.text
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 正規化されたURLを使用
        normalized_url = normalize_url(url)
        
        result = {
            'url': normalized_url,  # 正規化されたURLを使用
            'title': "取得エラー",
            'description': "取得エラー",
            'title_length': 0,
            'description_length': 0,
            'title_status': '❌ エラー',
            'description_status': '❌ エラー',
            'heading_issues': '❌ エラー',
            'english_only_headings': '❌ エラー',
            'images_without_alt': '❌ エラー',
            'html_syntax': '❌ エラー'
        }
        
        # タイトルの取得と重複チェック
        try:
            title = soup.title.string.strip() if soup.title else "タイトルなし"
            title_repetitions = check_keyword_repetition(title)
            title_status = []
            
            # 長さチェック
            if len(title) > 50:
                title_status.append('❌ 長すぎます（50文字以内推奨）')
            
            # 重複チェック
            if title_repetitions:
                title_status.append(f'⚠️ キーワードの重複: {", ".join(title_repetitions)}')
            
            # 問題がない場合
            if not title_status:
                title_status = ['✅ OK']
            
            result.update({
                'title': title,
                'title_length': len(title),
                'title_status': '<br>'.join(title_status)
            })
        except Exception as e:
            st.error(f"タイトル取得エラー: {str(e)}")
        
        # ディスクリプションの取得と重複チェック
        try:
            description = ""
            meta_desc = soup.find('meta', attrs={'name': re.compile('^[Dd]escription$')})
            if meta_desc:
                description = meta_desc.get('content', '').strip()
            if not description:
                og_desc = soup.find('meta', attrs={'property': 'og:description'})
                if og_desc:
                    description = og_desc.get('content', '').strip()
            
            description_repetitions = check_keyword_repetition(description)
            description_status = []
            
            # 長さチェック
            if len(description) > 140:
                description_status.append('❌ 長すぎます（140文字以内推奨）')
            
            # 重複チェック
            if description_repetitions:
                description_status.append(f'⚠️ キーワードの重複: {", ".join(description_repetitions)}')
            
            # 問題がない場合
            if not description_status:
                description_status = ['✅ OK']
            
            result.update({
                'description': description,
                'description_length': len(description),
                'description_status': '<br>'.join(description_status)
            })
        except Exception as e:
            st.error(f"ディスクリプション取得エラー: {str(e)}")
        
        # 見出しタグのチェック
        try:
            heading_issues, english_only_headings = check_heading_order(soup)
            # 問題がある場合は全ての問題を表示
            if heading_issues:
                result['heading_issues'] = '<br>'.join(heading_issues)
            else:
                result['heading_issues'] = '✅ OK'
                
            if english_only_headings:
                result['english_only_headings'] = '<br>'.join(english_only_headings)
            else:
                result['english_only_headings'] = '✅ OK'
        except Exception as e:
            st.error(f"見出しチェックエラー: {str(e)}")
        
        # 画像のalt属性チェック
        try:
            alt_check_result = check_image_alt(soup, url)
            result['images_without_alt'] = alt_check_result
        except Exception as e:
            st.error(f"画像チェックエラー: {str(e)}")
            result['images_without_alt'] = f'❌ エラー: {str(e)}'
        
        # HTML構文チェック
        try:
            syntax_errors = check_html_syntax(html_content)
            result['html_syntax'] = '\n'.join(syntax_errors) if syntax_errors else '✅ OK'
        except Exception as e:
            st.error(f"HTML構文チェックエラー: {str(e)}")
        
        return result
        
    except requests.RequestException as e:
        st.error(f"ページ取得エラー: {str(e)}")
        return {
            'url': normalize_url(url),
            'title': f'接続エラー: {str(e)}',
            'description': '接続エラー',
            'title_length': 0,
            'description_length': 0,
            'title_status': '❌ 接続エラー',
            'description_status': '❌ 接続エラー',
            'heading_issues': '❌ 接続エラー',
            'english_only_headings': '❌ 接続エラー',
            'images_without_alt': '❌ 接続エラー',
            'html_syntax': '❌ 接続エラー'
        }
    except Exception as e:
        st.error(f"予期せぬエラー: {str(e)}")
        return {
            'url': normalize_url(url),
            'title': f'エラー: {str(e)}',
            'description': 'エラー',
            'title_length': 0,
            'description_length': 0,
            'title_status': '❌ エラー',
            'description_status': '❌ エラー',
            'heading_issues': '❌ エラー',
            'english_only_headings': '❌ エラー',
            'images_without_alt': '❌ エラー',
            'html_syntax': '❌ エラー'
        }

def get_all_links(url, base_domain):
    """ページ内の全リンクを取得"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        # エンコーディングの自動検出と設定
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding
        
        # 404エラーの場合は空のセットを返す
        if response.status_code == 404:
            return set()
            
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
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
    except requests.exceptions.RequestException as e:
        if not isinstance(e, requests.exceptions.HTTPError) or e.response.status_code != 404:
            st.error(f"リンク取得エラー: {str(e)}")
        return set()
    except Exception as e:
        st.error(f"予期せぬエラー: {str(e)}")
        return set()

def is_preview_url(url):
    """プレビューURLかどうかをチェック"""
    preview_params = ['preview', 'preview_id', 'preview_nonce', '_thumbnail_id']
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    
    # プレビュー関連のパラメータが含まれているかチェック
    return any(param in query_params for param in preview_params)

def main():
    # ページ幅の設定
    st.set_page_config(
        page_title="WEBサイトSEOチェッカー",
        layout="wide",
        initial_sidebar_state="auto"
    )

    # スタムCSS
    st.markdown("""
        <style>
        .block-container {
            max-width: 1104px;  # 736px * 1.5
            padding-top: 1rem;
            padding-bottom: 1rem;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("🔍 WEBサイトSEOチェッカー")
    
    # バージョン情報と変更履歴
    with st.expander("📋 バージョン情報と変更履歴"):
        st.write("""
        **現在のバージョン: v1.0.0** 🚀 (2024.11.26 リリース)
        
        **変更履歴：**
        - v1.0.0 (2024.11.26)
          - ✨ 初回リリース
          - 🎯 基本的なSEO要素チェック機能を実装
        - v0.9.0 (2024.11.25)
          - 🔧 ベータ版リリース
          - 🧪 テスト運用開始
        """)
    
    st.write("""
    このツールは指定したドメインのSEO要素を自動的にチェックします。

    ### 📊 チェック項目：
    1. 📝 タイトルタグ（文字数と内容、50文字以内）
    2. 📄 メタディスクリプション（文字数と内容、140文字以内）
    3. 📑 見出し構造（h1〜h6の階層関係）
    4. 🖼️ 画像のalt属性（代替テキストの有無）
    5. 🔧 HTML構文（閉じタグの有無）の正確性

    ### 🚀 使い方：
    1. 🔗 チェックしたいウェブサイトのURLを入力
    2. ▶ 「チェック開始」ボタンをクリック
    3. ✨ 自動的に全ページをチェックし、結果を表示
    """)
    
    # 入力フォーム
    url = st.text_input("🌐 チェックしたいWEBサイトのURLを入力してください", "")
    
    if st.button("🔍 チェック開始") and url:
        base_domain = urlparse(url).netloc
        
        with st.spinner('🔄 サイトをチェック中...'):
            # 訪問済みURLを管理
            visited_urls = set()
            urls_to_visit = {url}
            results = []
            
            # プログレスバーの初期化
            progress_bar = st.progress(0)
            
            while urls_to_visit:
                current_url = urls_to_visit.pop()
                normalized_current_url = normalize_url(current_url)
                
                if normalized_current_url not in visited_urls:
                    visited_urls.add(normalized_current_url)
                    
                    # ページ情報の取得
                    page_info = get_page_info(current_url)
                    # 404エラー以外の結果のみを追加
                    if page_info is not None:
                        results.append(page_info)
                    
                    # 新しいリンクの取得
                    new_links = get_all_links(current_url, base_domain)
                    urls_to_visit.update(new_links - visited_urls)
                
                # プログレスバーの更新
                progress = len(visited_urls) / (len(visited_urls) + len(urls_to_visit))
                progress_bar.progress(min(progress, 1.0))
            
            # 結果の表示
            if results:
                df = pd.DataFrame(results)
                st.write(f"✅ チェック完了！ 合計{len(results)}ページをチェックしました。")
                
                # タブで結果を表示
                tab1, tab2, tab3, tab4, tab5 = st.tabs([
                    "📝 タイトル・ディスクリプション",
                    "📑 見出し構造",
                    "🔤 英語のみの見出し",
                    "🖼️ 画像alt属性",
                    "🔧 HTML構文"
                ])
                
                with tab1:
                    st.subheader("📊 タイトルとディスクリプションのチェック")
                    # HTMLをレンダリング可能にする
                    st.markdown("""
                        <style>
                        .dataframe a {
                            color: #1E88E5;
                            text-decoration: underline;
                        }
                        .dataframe td {
                            max-width: 300px;
                            white-space: normal !important;
                            padding: 8px !important;
                            vertical-align: top;
                        }
                        .dataframe th {
                            padding: 8px !important;
                            background-color: #f8f9fa;
                        }
                        .status-ok {
                            color: #28a745;
                            font-weight: bold;
                        }
                        .status-error {
                            color: #dc3545;
                            font-weight: bold;
                        }
                        .length-info {
                            color: #6c757d;
                            font-size: 0.9em;
                        }
                        </style>
                    """, unsafe_allow_html=True)

                    # デ��を整形
                    display_df = df.copy()
                    # URLの表示を修正
                    display_df['url'] = display_df['url'].apply(
                        lambda x: f'<a href="{x}" target="_blank">{unquote(x, encoding="utf-8")}</a>'
                    )
                    display_df['title'] = display_df.apply(
                        lambda row: f"{row['title']}<br><span class='length-info'>({row['title_length']}文字)</span>", 
                        axis=1
                    )
                    display_df['description'] = display_df.apply(
                        lambda row: f"{row['description']}<br><span class='length-info'>({row['description_length']}文字)</span>", 
                        axis=1
                    )
                    display_df['status'] = display_df.apply(
                        lambda row: f"タイトル: <span class='{get_status_class(row['title_status'])}'>{row['title_status']}</span><br>" +
                                  f"ディスクリプション: <span class='{get_status_class(row['description_status'])}'>{row['description_status']}</span>",
                        axis=1
                    )

                    # 表示するカラムを選択
                    st.write(display_df[['url', 'title', 'description', 'status']].to_html(
                        escape=False, index=False), unsafe_allow_html=True)

                with tab2:
                    st.subheader("📑 見出し構造のチェック")
                    # HTMLをレンダリング可能にする
                    st.markdown("""
                        <style>
                        .dataframe td {
                            max-width: 300px;
                            white-space: normal !important;
                            padding: 8px !important;
                            vertical-align: top;
                            word-break: break-all;
                        }
                        .dataframe th {
                            padding: 8px !important;
                            background-color: #f8f9fa;
                        }
                        </style>
                    """, unsafe_allow_html=True)
                    # URLカラムにリンクを追加
                    display_df2 = df.copy()
                    display_df2['url'] = display_df2['url'].apply(
                        lambda x: f'<a href="{x}" target="_blank">{unquote(x, encoding="utf-8")}</a>'
                    )
                    st.write(display_df2[['url', 'heading_issues']].to_html(escape=False, index=False), unsafe_allow_html=True)
                
                with tab3:
                    st.subheader("🔤 英語のみの見出しのチェック")
                    # URLカラムにリンクを追加
                    display_df3 = df.copy()
                    display_df3['url'] = display_df3['url'].apply(
                        lambda x: f'<a href="{x}" target="_blank">{unquote(x, encoding="utf-8")}</a>'
                    )
                    st.write(display_df3[['url', 'english_only_headings']].to_html(escape=False, index=False), unsafe_allow_html=True)
                
                with tab4:
                    st.subheader("🖼️ alt属性が設定されていない画像")
                    # DataFrameの表示前にHTMLをレンダリング可能にする
                    st.markdown("""
                        <style>
                        .dataframe a {
                            color: #1E88E5;
                            text-decoration: underline;
                            word-break: break-all;
                        }
                        .dataframe td {
                            max-width: 300px;
                            white-space: normal !important;
                            padding: 8px !important;
                            vertical-align: top;
                            word-break: break-all;
                        }
                        .dataframe th {
                            padding: 8px !important;
                            background-color: #f8f9fa;
                        }
                        .image-url {
                            display: block;
                            margin: 5px 0;
                            word-break: break-all;
                        }
                        </style>
                    """, unsafe_allow_html=True)
                    # URLカラムにリンクを追加
                    display_df4 = df.copy()
                    display_df4['url'] = display_df4['url'].apply(
                        lambda x: f'<a href="{x}" target="_blank">{unquote(x, encoding="utf-8")}</a>'
                    )
                    st.write(display_df4[['url', 'images_without_alt']].to_html(escape=False, index=False), unsafe_allow_html=True)
                
                with tab5:
                    st.subheader("🔧 HTML構文チェック")
                    # URLカラムにリンクを追加
                    display_df5 = df.copy()
                    display_df5['url'] = display_df5['url'].apply(
                        lambda x: f'<a href="{x}" target="_blank">{unquote(x, encoding="utf-8")}</a>'
                    )
                    st.write(display_df5[['url', 'html_syntax']].to_html(escape=False, index=False), unsafe_allow_html=True)
            else:
                st.error("チェック可能なページが見つかりませんでした。")

def get_status_class(status):
    """ステータスに応じたCSSクラスを返す"""
    if '✅' in status or 'OK' in status:
        return 'status-ok'
    return 'status-error'

if __name__ == "__main__":
    main() 