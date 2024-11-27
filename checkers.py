import re
import streamlit as st
from html.parser import HTMLParser
from bs4 import BeautifulSoup
from utils import contains_japanese
from janome.tokenizer import Tokenizer

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
        # PHPコー
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
    
    has_errors = False
    
    for tag_name in important_tags:
        # タグの開始位置を全て取得
        tag_pattern = re.compile(f'<{tag_name}[^>]*>')
        start_positions = [(i + 1, m.start(), m.group()) for i, line in enumerate(lines) 
                          for m in re.finditer(tag_pattern, line)]
        
        # タグの終了位置を全て取得
        end_pattern = re.compile(f'</{tag_name}>')
        end_positions = [(i + 1, m.start()) for i, line in enumerate(lines) 
                        for m in re.finditer(end_pattern, line)]
        
        # 開始タグと終了タグの数を比較
        if len(start_positions) > len(end_positions):
            # 閉じられていないタグの位置を特定
            unclosed_tags = []
            for i, (line_num, pos, tag_content) in enumerate(start_positions):
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
                        # 行全体を認てじグが存在するかチェック
                        full_line = original_line
                        if f'</{tag_name}>' in full_line:
                            continue  # 同じ行に閉じタグがある場合はスキップ
                        
                        # コンテキストから実際のタグを抽出
                        tag_match = re.search(f'<{tag_name}[^>]*>', context)
                        if tag_match:
                            tag_content = tag_match.group()
                        
                        unclosed_tags.append((line_num, context, tag_content))
            
            if unclosed_tags:
                has_errors = True
                for line_num, context, tag_content in unclosed_tags:
                    error_msg = f"❌ 警告: {tag_name}タグの閉じ忘れが1個あります:\n"
                    error_msg += f"→ 行 {line_num}: {tag_content}"
                    syntax_errors.append(error_msg)
    
    if not has_errors:
        return ['✅ OK']
    
    return syntax_errors

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
    
    # URLからベースURLを取得
    base_url = '/'.join(url.split('/')[:3])  # http(s)://domain.com までを取得
    
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
            # データURLやbase64エンコードされた画像、PDFファイルは除外
            if not src.startswith('data:') and not src.lower().endswith('.pdf'):
                total_images += 1
                alt = img.get('alt', '').strip()
                if not alt:
                    # 相対パを完全なURLに換
                    if src.startswith('/'):
                        full_src = base_url + src
                    elif src.startswith('../'):
                        # ../を除去して、ベースURLに追加
                        full_src = base_url + '/' + '/'.join(src.split('/')[1:])
                    elif not src.startswith(('http://', 'https://')):
                        full_src = base_url + '/' + src
                    else:
                        full_src = src
                        
                    if full_src not in images_without_alt:
                        images_without_alt.append(full_src)
    
    # 結果を返す
    if total_images == 0:
        return '- 画像なし'
    elif images_without_alt:
        # 番号付きのリストを作成
        result_lines = []
        for i, img_url in enumerate(images_without_alt, 1):
            result_lines.append(f'{i}: {img_url}')
        return '❌ alt属性なし:\n' + '\n'.join(result_lines)
    else:
        return '✅ OK'

def check_keyword_repetition(text):
    """
    テキスト内のキーワード重複をチェックする（形態素解析使用）
    """
    if not text or len(text.strip()) == 0:
        return "✅ OK"

    # 診療科関連の用語（重複チェック対象外）
    medical_terms = {
        '内科', '外科', '眼科', '歯科', '小児歯科', '矯正歯科', '審美歯科', '口腔外科',
        '消化器内科', '循環器内科', '脳神経内科', '消化器外科', '心臓血管外科',
        '病院', 'クリニック', '医院', '診療所', '形成外科', '美容外科', '皮膚科',
        '血管外科', '美容皮膚科', '婦人科'
    }

    # 医療用語から抽出する部分文字列（2文字以上）
    medical_substrings = set()
    for term in medical_terms:
        # 2文字以上の部分文字列を抽出
        for i in range(len(term)-1):
            for j in range(i+2, len(term)+1):
                substring = term[i:j]
                if len(substring) >= 2:
                    medical_substrings.add(substring)

    # 無視する品詞
    ignore_pos = {
        '助詞', '助動詞', '記号', '接続詞', '感動詞', '副詞', '連体詞'
    }

    # Janomeのトークナイザーを初期化
    tokenizer = Tokenizer()

    # キーワードの出現回数を記録（表層形で記録）
    keyword_counts = {}
    
    # テキストを形態素解析
    tokens = tokenizer.tokenize(text)
    for token in tokens:
        # 形態素情報を取得
        pos = token.part_of_speech.split(',')[0]  # 品詞
        surface = token.surface  # 表層形

        # 以下の条件のトークンはスキップ
        if (pos in ignore_pos or  # 無視する品詞
            len(surface) < 2 or  # 1文字の単語
            surface in medical_terms or  # 完全一致する医療用語
            surface in medical_substrings):  # 医療用語の部分文字列
            continue

        # 名詞のみを対象とする（より厳密なチェック）
        if pos == '名詞':
            if surface not in keyword_counts:
                keyword_counts[surface] = 0
            keyword_counts[surface] += 1

    # 重複チェック結果の生成（3回以上出現する単語のみ）
    duplicates = {word: count for word, count in keyword_counts.items() if count >= 3}
    
    if not duplicates:
        return "✅ OK"
    
    # 重複結果のメッセージ作成
    message = "⚠️ キーワードの重複：\n"
    for i, (word, count) in enumerate(sorted(duplicates.items(), key=lambda x: x[1], reverse=True), 1):
        message += f"{i}. '{word}' が{count}回出現\n"
    
    return message