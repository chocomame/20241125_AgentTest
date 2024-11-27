import re
import streamlit as st
from html.parser import HTMLParser
from bs4 import BeautifulSoup
from utils import contains_japanese

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
        # PHPコー��
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
                        # 行全体を認てじ��グが存在するかチェック
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
                    # 相対パを完全なURLに���換
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
    """テキスト内のキーワード重複をチェック"""
    if not text:
        return ['✅ OK']
    
    # 特定のストップワード（無視する単語）を定義
    stop_words = {'の', 'や', 'が', 'を', 'に', 'へ', 'で', 'から', 'まで', 'り', 'も', 'は', '・', '|', '-', 'です', 'ます', 'した', 'する', 'いる', 'ある', 'れる', 'られる', 'など', 'どの', 'その', 'これ', 'それ', 'あれ', 'この', 'さん', '様', '氏', '方', 'ない', 'あり', 'なし', 'とき', 'もの', 'こと', 'ところ', 'できる', 'おり', 'なる', 'いく', 'しまう', 'たい', 'ます', 'です', 'ください'}
    
    # 診療科関連の用語（これらは重複をカウントしない）
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
        '病院', 'クリニック', '医院', '診療所', '専門医'
    }

    # テキストの前処理
    # 括弧を空白に置換
    text = re.sub(r'[（）「」『』【】［］\[\]]', ' ', text)
    
    # まず、文を句読点で分割
    sentences = re.split(r'[、。,.]+', text)
    
    # キーワードの候補を収集
    keyword_candidates = set()
    # 2文字以上の連続した漢字、ひらがな、カタカナを抽出するパターン
    pattern = r'[一-龯ぁ-んァ-ヶー]{2,}'
    
    # 各文から単語を抽出
    for sentence in sentences:
        # 空白で分割して基本単位を取得
        words = sentence.strip().split()
        for word in words:
            # 各単語から日本語文字列を抽出
            matches = re.finditer(pattern, word)
            for match in matches:
                keyword = match.group()
                if keyword not in stop_words and keyword not in medical_specialties:
                    # 単語の先頭から始まる部分文字列のみを候補とする
                    for length in range(2, len(keyword) + 1):
                        sub_keyword = keyword[:length]
                        if len(sub_keyword) >= 2:
                            keyword_candidates.add(sub_keyword)
    
    # キーワードの出現回数をカウント
    keyword_counts = {}
    
    # 各キーワード候補について、テキスト全体での出現回数をカウント
    for keyword in keyword_candidates:
        count = len(re.findall(re.escape(keyword), text))
        if count > 0:
            keyword_counts[keyword] = count
    
    # 3回以上出現するキーワードを抽出（長さ順にソート）
    repeated_keywords = [(k, v) for k, v in keyword_counts.items() if v >= 3]
    repeated_keywords.sort(key=lambda x: len(x[0]), reverse=True)
    
    # 包含関係にあるキーワードを除外
    filtered_keywords = []
    for i, (keyword1, count1) in enumerate(repeated_keywords):
        is_included = False
        # 先頭からの部分文字列でない場合は除外
        for j, (keyword2, count2) in enumerate(repeated_keywords):
            if i != j and keyword2.find(keyword1) == 0:  # 先頭からの一致のみを考慮
                is_included = True
                break
        if not is_included:
            filtered_keywords.append((keyword1, count1))
    
    # 医療関連用語を除外
    final_keywords = []
    for keyword, count in filtered_keywords:
        # キーワードが医療関連用語に完全一致する場合は除外
        if keyword not in medical_specialties:
            # キーワードが医療関連用語の一部として含まれる場合も除外
            is_medical_term = False
            for medical_term in medical_specialties:
                if medical_term.find(keyword) != -1 or keyword.find(medical_term) != -1:
                    is_medical_term = True
                    break
            if not is_medical_term:
                final_keywords.append((keyword, count))
    
    if not final_keywords:
        return ['✅ OK']
    
    # 警告メッセージを生成（詳細な形式）
    warnings = ['⚠️ キーワードの重複：']
    for i, (keyword, count) in enumerate(final_keywords, 1):
        warnings.append(f"{i}. '{keyword}' が{count}回出現")
    
    return warnings