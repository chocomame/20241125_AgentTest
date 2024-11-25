import streamlit as st
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
from urllib.parse import urljoin, urlparse, unquote
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
    
    # PHPコードと特殊文字を一時的なプレースホルダーに置換
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
    """URLを正規化（末尾のスラッシュを統一し、日本語をデコード）"""
    # URLデコード（日本語などを読める形式に）
    decoded_url = unquote(url)
    # 末尾のスラッシュを統一（最後にスラッシュをつける）
    if not decoded_url.endswith('/'):
        decoded_url += '/'
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
    
    for heading in headings:
        current_level = int(heading.name[1])
        heading_text = heading.get_text().strip()
        
        # 見出しレベルのチェック
        if prev_level > 0 and current_level - prev_level > 1:
            heading_issues.append(f"見出しの順序が不適切: h{prev_level}からh{current_level}に飛んでいます")
        
        # 英語のみのチェック
        if heading_text and not contains_japanese(heading_text):
            # 数字とアルファベットのみで構成されているかチェック
            if re.match(r'^[a-zA-Z0-9\s\-_.,!?]*$', heading_text):
                english_only_headings.append(f"{heading.name}: {heading_text}")
        
        prev_level = current_level
    
    return heading_issues, english_only_headings

def check_image_alt(soup, url):
    """画像のalt属性をチェック"""
    # /blog/または/category/を含むURLの場合はチェックをスキップ
    if '/blog/' in url or '/category/' in url:
        return 'skip'
        
    images_without_alt = []
    total_images = 0
    
    # picture要素内のimg要素を確認
    for picture in soup.find_all('picture'):
        img = picture.find('img')
        if img and img.get('src'):  # srcが存在する場合のみ処理
            total_images += 1
            alt = img.get('alt', '').strip()
            src = img.get('src', '')
            if not alt:
                images_without_alt.append(src)
    
    # すべてのimg要素を検索（コンテナやクラスに関係なく）
    all_images = soup.find_all('img', recursive=True)
    valid_images = [img for img in all_images if img.get('src') or img.get('srcset')]  # 有効なsrcまたはsrcsetを持つ画像のみ
    
    for img in valid_images:
        # picture要素内のimgは既にチェック済みなのでスキップ
        if not img.find_parent('picture'):
            total_images += 1
            alt = img.get('alt', '').strip()
            src = img.get('src', '') or img.get('srcset', '').split(',')[0].strip().split(' ')[0]
            if not alt:
                images_without_alt.append(src)
    
    # 結果を返す
    if not total_images:
        return 'no_images'
    elif images_without_alt:
        return images_without_alt
    elif total_images > 0:
        return 'ok'
    else:
        return 'no_images'

def get_page_info(url):
    """ページのタイトルとディスクリプションを取得"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        html_content = response.text
        soup = BeautifulSoup(html_content, 'html.parser')
        
        result = {
            'url': normalize_url(url),
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
        
        # タイトルの取得
        try:
            title = soup.title.string.strip() if soup.title else "タイトルなし"
            result.update({
                'title': title,
                'title_length': len(title),
                'title_status': '❌ 長すぎます' if len(title) > 50 else '✅ OK'
            })
        except Exception as e:
            st.error(f"タイトル取得エラー: {str(e)}")
        
        # ディスクリプションの取得
        try:
            description = ""
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc:
                description = meta_desc.get('content', '').strip()
            result.update({
                'description': description,
                'description_length': len(description),
                'description_status': '❌ 長すぎます' if len(description) > 140 else '✅ OK'
            })
        except Exception as e:
            st.error(f"ディスクリプション取得エラー: {str(e)}")
        
        # 見出しタグのチェック
        try:
            heading_issues, english_only_headings = check_heading_order(soup)
            result.update({
                'heading_issues': '\n'.join(heading_issues) if heading_issues else '✅ OK',
                'english_only_headings': '\n'.join(english_only_headings) if english_only_headings else '✅ OK'
            })
        except Exception as e:
            st.error(f"見出しチェックエラー: {str(e)}")
        
        # 画像のalt属性チェック
        try:
            alt_check_result = check_image_alt(soup, url)
            if alt_check_result == 'skip':
                if '/blog/' in url:
                    images_without_alt_str = '✅ ブログページのためスキップ'
                elif '/category/' in url:
                    images_without_alt_str = '✅ カテゴリーページのためスキップ'
                else:
                    images_without_alt_str = '✅ スキップ'
            elif alt_check_result == 'no_images':
                images_without_alt_str = '- 画像なし'
            elif alt_check_result == 'ok':
                images_without_alt_str = '✅ OK'
            elif isinstance(alt_check_result, list) and alt_check_result:
                images_without_alt_str = '❌ alt属性なし:\n' + '\n'.join(alt_check_result)
            else:
                images_without_alt_str = '- 画像なし'
            result['images_without_alt'] = images_without_alt_str
        except Exception as e:
            st.error(f"画像チェックエラー: {str(e)}")
        
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
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            absolute_url = urljoin(url, href)
            
            # アンカーリンクとドメイン外のリンクを除外
            if not is_anchor_link(absolute_url) and is_same_domain(absolute_url, base_domain):
                # URLを正規化して追加
                normalized_url = normalize_url(absolute_url)
                links.add(normalized_url)
        
        return links
    except Exception as e:
        st.error(f"リンク取得エラー: {str(e)}")
        return set()

def main():
    st.title("WEBサイトSEOチェッカー")
    st.write("指定したドメインのタイトル、ディスクリプション、見出し、画像のalt、HTML構文をチェックします")
    
    # 入力フォーム
    url = st.text_input("チェックしたいWEBサイトのURLを入力してください", "")
    
    if st.button("チェック開始") and url:
        base_domain = urlparse(url).netloc
        
        with st.spinner('サイトをチェック中...'):
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
                st.write(f"チェック完了！ 合計{len(results)}ページをチェックしました。")
                
                # タブで結果を表示
                tab1, tab2, tab3, tab4, tab5 = st.tabs([
                    "タイトル・ディスクリプション",
                    "見出し構造",
                    "英語のみの見出し",
                    "画像alt属性",
                    "HTML構文"
                ])
                
                with tab1:
                    st.subheader("タイトルとディスクリプションのチェック")
                    st.dataframe(
                        df[['url', 'title', 'title_length', 'title_status', 
                            'description', 'description_length', 'description_status']]
                    )
                
                with tab2:
                    st.subheader("見出し構造のチェック")
                    st.dataframe(df[['url', 'heading_issues']])
                
                with tab3:
                    st.subheader("英語のみの見出しのチェック")
                    st.dataframe(df[['url', 'english_only_headings']])
                
                with tab4:
                    st.subheader("alt属性が設定されていない画像")
                    st.dataframe(df[['url', 'images_without_alt']])
                
                with tab5:
                    st.subheader("HTML構文チェック")
                    st.dataframe(df[['url', 'html_syntax']])
                
                # CSVダウンロードボタン
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="結果をCSVでダウンロード",
                    data=csv,
                    file_name="seo_check_results.csv",
                    mime="text/csv"
                )
            else:
                st.error("チェック可能なページが見つかりませんでした。")

if __name__ == "__main__":
    main() 