import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
from urllib.parse import urlparse, unquote
from utils import normalize_url, is_preview_url, get_all_links
from checkers import (
    check_html_syntax,
    check_heading_order,
    check_image_alt,
    check_keyword_repetition
)

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
                'html_syntax': '- スキップ',
                'status_code': 0,
                'related_urls': []  # 関連URLのリストを追加
            }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        # エンコーディングの自動検出と設定
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding
        elif 'charset' in response.headers.get('content-type', '').lower():
            response.encoding = response.apparent_encoding
        else:
            response.encoding = 'utf-8'
        
        # ステータスコードを保存
        status_code = response.status_code
        
        # 404エラーの場合は特別な結果を返す
        if status_code == 404:
            return {
                'url': normalize_url(url),
                'title': "404 エラー",
                'description': "ページが見つかりません",
                'title_length': 0,
                'description_length': 0,
                'title_status': '❌ 404エラー',
                'description_status': '❌ 404エラー',
                'heading_issues': '❌ 404エラー',
                'english_only_headings': '❌ 404エラー',
                'images_without_alt': '❌ 404エラー',
                'html_syntax': '❌ 404エラー',
                'status_code': 404,
                'related_urls': []  # 関連URLのリストを追加
            }
        
        response.raise_for_status()
        html_content = response.text
        
        # BeautifulSoupでパース（エンコーディングを指定）
        soup = BeautifulSoup(html_content, 'html.parser', from_encoding=response.encoding)
        
        # 正規化されたURLを使用
        normalized_url = normalize_url(url)
        
        result = {
            'url': normalized_url,
            'title': "取得エラー",
            'description': "取得エラー",
            'title_length': 0,
            'description_length': 0,
            'title_status': '❌ エラー',
            'description_status': '❌ エラー',
            'heading_issues': '❌ エラー',
            'english_only_headings': '❌ エラー',
            'images_without_alt': '❌ エラー',
            'html_syntax': '❌ エラー',
            'status_code': status_code,
            'related_urls': []  # 関連URLのリストを追加
        }
        
        # タイトルの取得と重複チェック
        try:
            title = soup.title.string.strip() if soup.title else "タイトルなし"
            # タイトルのエンコーディングを確認して修正
            if isinstance(title, bytes):
                title = title.decode(response.encoding)
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
        except Exception:
            pass
        
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
            
            # ディスクリプションのエンコーディングを確認して修正
            if isinstance(description, bytes):
                description = description.decode(response.encoding)
            
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
        except Exception:
            pass
        
        # 見出し構造のチェック
        try:
            heading_issues, english_only_headings = check_heading_order(soup)
            result['heading_issues'] = '<br>'.join(heading_issues) if heading_issues else '✅ OK'
            result['english_only_headings'] = '<br>'.join(english_only_headings) if english_only_headings else '✅ OK'
        except Exception:
            pass
        
        # 画像のalt属性チェック
        try:
            alt_check_result = check_image_alt(soup, url)
            result['images_without_alt'] = alt_check_result
        except Exception:
            pass
        
        # HTML構文チェック
        try:
            syntax_errors = check_html_syntax(html_content)
            result['html_syntax'] = syntax_errors[0]
            
            # 関連URLを抽出（エラーメッセージから）
            if 'https://' in result['html_syntax']:
                related_urls = re.findall(r'https://[^\s<>"\']+', result['html_syntax'])
                result['related_urls'] = related_urls
        except Exception:
            pass
        
        return result
        
    except requests.RequestException:
        return {
            'url': normalize_url(url),
            'title': "接続ラー",
            'description': "接続エラー",
            'title_length': 0,
            'description_length': 0,
            'title_status': '❌ 接続エラー',
            'description_status': '❌ 接続エラー',
            'heading_issues': '❌ 接続エラー',
            'english_only_headings': '❌ 接続エラー',
            'images_without_alt': '❌ 接続エラー',
            'html_syntax': '❌ 接続エラー',
            'status_code': 0,
            'related_urls': []  # 関連URLのリストを追加
        }

def main():
    # ページ幅の設定
    st.set_page_config(
        page_title="検品チェック6選",
        layout="wide",
        initial_sidebar_state="auto"
    )

    # カスタムCSS
    st.markdown("""
        <style>
        .block-container {
            max-width: 1104px;
            padding-top: 1rem;
            padding-bottom: 1rem;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("🔍 検品チェック6選")
    
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
    
    # チェック項目
    with st.expander("📊 チェック項目の詳細"):
        st.write("""
        1. 📝 タイトルタグ
           - 文字数（50文字以内）
           - キーワードの重複チェック（診療科名を除く）
           - 診療科名は重複を許容

        2. 📄 メタディスクリプション
           - 文字数（140文字以内）
           - キーワードの重複チェック（診療科名を除く）
           - 診療科名は重複を許容

        3. 📑 見出し構造（h1〜h6の階層関係）
           - 見出しレベルの適切な階層構造
           - 飛び階層のチェック

        4. 🖼️ 画像のalt属性
           - 代替テキストの有無
           - ブログ・カテゴリーページはスキップ

        5. 🔧 HTML構文
           - 閉じタグの有無
           - タグの正確性チェック

        6. ⚠️ 404エラーページ
           - 存在しないページの検出
           - リンク切れの確認
        """)
    
    # 使い方
    with st.expander("🚀 使い方"):
        st.write("""
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
            not_found_pages = []  # 404ページを記録
            
            # プログレスバーの初期化
            progress_bar = st.progress(0)
            
            while urls_to_visit:
                current_url = urls_to_visit.pop()
                normalized_current_url = normalize_url(current_url)
                
                if normalized_current_url not in visited_urls:
                    visited_urls.add(normalized_current_url)
                    
                    # ページ情報の取得
                    page_info = get_page_info(current_url)
                    
                    # 404エラーのページを記録
                    if page_info and page_info.get('status_code') == 404:
                        not_found_pages.append(page_info)
                    # 404以外のページを結果に追加
                    elif page_info is not None:
                        results.append(page_info)
                    
                    # 新しいリンクの取得（404ページ以外）
                    if page_info and page_info.get('status_code') != 404:
                        try:
                            response = requests.get(current_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                            soup = BeautifulSoup(response.text, 'html.parser')
                            new_links = get_all_links(current_url, base_domain, soup)
                            urls_to_visit.update(new_links - visited_urls)
                        except Exception:
                            pass
                
                # プログレスバーの更新
                progress = len(visited_urls) / (len(visited_urls) + len(urls_to_visit))
                progress_bar.progress(min(progress, 1.0))
            
            # 結果の表示
            if results or not_found_pages:
                df = pd.DataFrame(results)
                not_found_df = pd.DataFrame(not_found_pages) if not_found_pages else None
                
                st.write(f"✅ チェック完了！ 合計{len(results)}ページをチェックしました。")
                if not_found_pages:
                    st.write(f"⚠️ {len(not_found_pages)}件の404エラーページが見つかりました。")
                
                # タブで結果を表示
                tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
                    "📝 タイトル・ディスクリプション",
                    "📑 見出し構造",
                    "🔤 英語のみの見出し",
                    "🖼️ 画像alt属性",
                    "🔧 HTML構文",
                    "⚠️ 404エラー"
                ])
                
                with tab1:
                    st.subheader("📊 タイトルとディスクリプションのチェック")
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
                    
                    # データを整形
                    display_df = df.copy()
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
                    
                    # ステータスクラスとメッセージの設定
                    def format_status(status_text):
                        if '✅ OK' in status_text:
                            return f'<span class="status-ok">{status_text}</span>'
                        elif '❌' in status_text:
                            return f'<span class="status-error">{status_text}</span>'
                        elif '⚠️' in status_text:
                            return f'<span class="status-warning">{status_text}</span>'
                        return status_text

                    display_df['status'] = display_df.apply(
                        lambda row: (
                            f"タイトル: {format_status(row['title_status'])}<br>" +
                            f"ディスクリプション: {format_status(row['description_status'])}"
                        ),
                        axis=1
                    )
                    
                    # 表示するカラムを選択
                    st.write(display_df[['url', 'title', 'description', 'status']].to_html(
                        escape=False, index=False), unsafe_allow_html=True)
                
                with tab2:
                    st.subheader("📑 見出し構造のチェック")
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
                    # カスタムCSSを追加
                    st.markdown("""
                        <style>
                        .dataframe td {
                            max-width: 500px;
                            white-space: normal !important;
                            word-wrap: break-word;
                            word-break: break-all;
                        }
                        .dataframe th {
                            white-space: normal !important;
                            word-wrap: break-word;
                            word-break: break-all;
                        }
                        </style>
                    """, unsafe_allow_html=True)
                    
                    # URLカラムにリンクを追加
                    display_df4 = df.copy()
                    display_df4['url'] = display_df4['url'].apply(
                        lambda x: f'<a href="{x}" target="_blank">{unquote(x, encoding="utf-8")}</a>'
                    )
                    # 画像URLをクリック可能なリンクに変換
                    display_df4['images_without_alt'] = display_df4['images_without_alt'].apply(
                        lambda x: x if x in ['✅ OK', '- 画像なし', 'skip'] else
                        '<br>'.join([
                            f'{line.split(": ")[0]}: <a href="{line.split(": ")[1]}" target="_blank">{line.split(": ")[1]}</a>'
                            for line in x.split('\n')[1:]  # 最初の行（❌ alt属性なし:）をスキップ
                        ])
                    )
                    st.write(display_df4[['url', 'images_without_alt']].to_html(escape=False, index=False), unsafe_allow_html=True)
                
                with tab5:
                    st.subheader("🔧 HTML構文チェック")
                    
                    # カスタムCSSを追加
                    st.markdown("""
                        <style>
                        .html-error {
                            color: #dc3545;
                            margin-bottom: 8px;
                        }
                        .html-ok {
                            color: #28a745;
                            font-weight: bold;
                            margin: 0;
                            padding: 0;
                            line-height: 1;
                        }
                        .error-line {
                            color: #666;
                            margin-left: 20px;
                            display: block;
                            font-family: monospace;
                        }
                        .error-tag {
                            color: #e83e8c;
                            background-color: #f8f9fa;
                            padding: 2px 4px;
                            border-radius: 3px;
                            font-family: monospace;
                        }
                        td {
                            vertical-align: middle !important;
                            padding: 8px !important;
                        }
                        </style>
                    """, unsafe_allow_html=True)
                    
                    # URLカラムにリンクを追加
                    display_df5 = df.copy()
                    
                    # HTML構文エラーの表示を整形
                    def format_html_syntax(row):
                        html_syntax = row['html_syntax']
                        
                        if html_syntax == '✅ OK':
                            return '<div class="html-ok">✅ OK</div>'
                        
                        # エラーメッセージを改行で分割
                        lines = html_syntax.split('\n')
                        if len(lines) >= 2:
                            main_error = lines[0]  # "❌ 警告: divタグの閉じ忘れが1個あります:"
                            detail_line = lines[1]  # "→ 行 470: <div class='xxx'>"
                            
                            # 行番号とタグを分離
                            line_parts = detail_line.split(': ', 1)
                            if len(line_parts) == 2:
                                line_info, tag_content = line_parts
                                formatted_error = f'<div class="html-error">{main_error}</div>'
                                formatted_error += f'<span class="error-line">{line_info}: <span class="error-tag">{tag_content}</span></span>'
                                return formatted_error
                        
                        return html_syntax
                    
                    # URLをリンクに変換
                    display_df5['url'] = display_df5['url'].apply(
                        lambda x: f'<a href="{x}" target="_blank">{unquote(x, encoding="utf-8")}</a>'
                    )
                    
                    # HTML構文エラーを整形
                    display_df5['html_syntax'] = display_df5.apply(format_html_syntax, axis=1)
                    
                    # データフレームを表示
                    st.write(display_df5[['url', 'html_syntax']].to_html(
                        escape=False, 
                        index=False,
                        classes=['dataframe'],
                        table_id='html-syntax-table'
                    ), unsafe_allow_html=True)
                
                with tab6:
                    st.subheader("⚠️ 404エラーページ")
                    if not_found_df is not None and not not_found_df.empty:
                        # URLカラムにリンクを追加
                        not_found_df['url'] = not_found_df['url'].apply(
                            lambda x: f'<a href="{x}" target="_blank">{unquote(x, encoding="utf-8")}</a>'
                        )
                        st.write(not_found_df[['url']].to_html(escape=False, index=False), unsafe_allow_html=True)
                    else:
                        st.write("✅ 404エラーページは見つかりませんでした。")
            else:
                st.write("チェック可能なページが見つかりませんでした。")

def get_status_class(status):
    """ステータスに応じたCSSクラスを返す"""
    if '✅' in status or 'OK' in status:
        return 'status-ok'
    return 'status-error'

if __name__ == "__main__":
    main() 