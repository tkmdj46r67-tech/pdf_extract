import argparse
from pathlib import Path
import re
import sys
from html.parser import HTMLParser

# --- DEPENDENCY CHECKING BLOCK ---
REQUIRED_PACKAGES = {
    "fitz": "pip install pymupdf",
    "nltk": "pip install nltk",
    "wordninja": "pip install wordninja",
    "ebooklib": "pip install ebooklib"
}

missing_packages = []
for package, install_cmd in REQUIRED_PACKAGES.items():
    try:
        if package == "fitz":
            import fitz
        else:
            __import__(package)
    except ImportError:
        missing_packages.append(install_cmd.split()[-1])

if missing_packages:
    print("\n" + "="*60)
    print("❌ ERROR: Missing Required Python Dependencies!")
    print("="*60)
    print("The following packages are required but not installed on this machine:")
    for pkg in missing_packages:
        print(f"  • {pkg}")
    print("\nTo resolve this issue, please run the following installation command:")
    print(f"  pip install {' '.join(missing_packages)}")
    print("="*60 + "\n")
    sys.exit(1)
# ----------------------------------

import ssl
import fitz  # PyMuPDF
import nltk
import wordninja
from ebooklib import epub
import ebooklib

# Fix for macOS SSL Certificate verification error
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# Ensure the NLTK words list is downloaded safely
try:
    nltk.data.find("corpora/words")
except LookupError:
    print("📥 First-time setup: Downloading English dictionary corpus...")
    nltk.download("words", quiet=True)

from nltk.corpus import words
ENGLISH_WORDS = set(word.lower() for word in words.words())

class EPUBHTMLToMarkdownParser(HTMLParser):
    """A lightweight HTML parser to convert EPUB chapter content into Markdown formatting."""
    def __init__(self):
        super().__init__()
        self.result = []
        self.style_stack = []

    def handle_starttag(self, tag, attrs):
        if tag in ['strong', 'b']:
            self.style_stack.append('**')
            self.result.append('**')
        elif tag in ['em', 'i']:
            self.style_stack.append('*')
            self.result.append('*')
        elif tag in ['p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div']:
            self.result.append('
')

    def handle_endtag(self, tag):
        if tag in ['strong', 'b']:
            if self.style_stack and self.style_stack[-1] == '**':
                self.style_stack.pop()
                self.result.append('**')
        elif tag in ['em', 'i']:
            if self.style_stack and self.style_stack[-1] == '*':
                self.style_stack.pop()
                self.result.append('*')

    def handle_data(self, data):
        self.result.append(data)

    def get_markdown(self):
        return "".join(self.result)

def extract_markdown_from_pdf(pdf_path):
    """Opens a PDF and extracts text, preserving bold and italic styles."""
    doc = fitz.open(pdf_path)
    extracted_text = []

    for page_num, page in enumerate(doc, start=1):
        text_page = page.get_text("dict", flags=fitz.TEXTFLAGS_SEARCH)
        page_lines = []
        
        for block in text_page["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                line_text = ""
                for span in line["spans"]:
                    font_flags = span["flags"]
                    text_span = span["text"]
                    
                    if not text_span.strip():
                        line_text += text_span
                        continue

                    is_italic = bool(font_flags & 2)
                    is_bold = bool(font_flags & 16) or "bold" in span["font"].lower()

                    styled_span = text_span.strip()
                    if is_bold and is_italic:
                        styled_span = f"***{styled_span}***"
                    elif is_bold:
                        styled_span = f"**{styled_span}**"
                    elif is_italic:
                        styled_span = f"*{styled_span}*"
                        
                    if text_span.startswith(" "): styled_span = " " + styled_span
                    if text_span.endswith(" "): styled_span = styled_span + " "
                    line_text += styled_span
                
                if line_text.strip():
                    page_lines.append(line_text)
                    
        if page_lines:
            page_content = "
".join(page_lines)
            extracted_text.append(f"--- Page {page_num} ---
{page_content}")

    return "

".join(extracted_text)

def extract_markdown_from_epub(epub_path):
    """Opens an EPUB file and extracts text, preserving basic bold and italic styles via Markdown."""
    book = epub.read_epub(str(epub_path))
    extracted_text = []
    item_count = 1

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            html_content = item.get_content().decode('utf-8', errors='ignore')
            parser = EPUBHTMLToMarkdownParser()
            parser.feed(html_content)
            markdown_content = parser.get_markdown()
            
            if markdown_content.strip():
                extracted_text.append(f"--- Section {item_count} ---
{markdown_content.strip()}")
                item_count += 1
                
    return "

".join(extracted_text)

def is_header_or_footer(line):
    """Identifies common book artifacts like running headers and Roman numeral strings."""
    stripped = re.sub(r'\*+', '', line).strip().lower()
    if not stripped:
        return False
        
    if re.search(r'[ex•\[\s]*(?:x[vlcx]*|v[ix]*|i[vx]*)[ex•\]\s]*', stripped):
        if any(term in stripped for term in ["castxe", "castle", "dick", "life", "high", "purr", "philip"]):
            return True
            
    if re.match(r'^page\s+\d+$|^\d+$', stripped):
        return True
        
    return False

def is_valid_word(word):
    clean = re.sub(r'[^\w]', '', word).lower()
    if not clean:
        return False
    if clean.isdigit():
        return True
    if len(clean) == 1:
        return clean in ['a', 'i', 'o']
    return clean in ENGLISH_WORDS

def check_line_quality(line, max_punctuation_ratio=0.15, min_real_word_ratio=0.45):
    clean_line = re.sub(r'\*+', '', line).strip()
    if not clean_line:
        return False

    if is_header_or_footer(line):
        return False

    total_chars = len(clean_line)
    alnum_chars = len([c for c in clean_line if c.isalnum() or c.isspace()])
    punct_ratio = (total_chars - alnum_chars) / total_chars
    if punct_ratio > max_punctuation_ratio:
        return False

    alpha_only = "".join([c for c in clean_line if c.isalpha()]).lower()
    if len(alpha_only) > 3:
        vowels = len(re.findall(r'[aeiouy]', alpha_only))
        if vowels == 0 or (len(alpha_only) - vowels) == 0:
            return False

    tokens = clean_line.split()
    if not tokens:
        return False
        
    valid_count = sum(1 for token in tokens if is_valid_word(token))
    real_word_ratio = valid_count / len(tokens)
    
    return real_word_ratio >= min_real_word_ratio

def clean_markdown_artifacts(input_txt_path):
    """Processes extracted markdown structural lines and filters noise or splits."""
    cleaned_lines = []
    
    with open(input_txt_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line in lines:
        if line.strip().startswith("--- Page") or line.strip().startswith("--- Section"):
            cleaned_lines.append(line)
            continue
            
        if check_line_quality(line):
            cleaned_lines.append(line)

    full_text = "".join(cleaned_lines)
    full_text = re.sub(r'
+--- Page \d+ ---
+', r' ', full_text)
    full_text = re.sub(r'
+--- Section \d+ ---
+', r' ', full_text)

    # --- STYLE-AWARE UN-GLUING INTERPRETER ---
    final_tokens = []
    for token in full_text.split(' '):
        if not token.strip(): continue
        
        clean_word = re.sub(r'[^\w]', '', token)
        
        if len(clean_word) > 4 and clean_word.isalpha() and clean_word.lower() not in ENGLISH_WORDS:
            split_pieces = wordninja.split(clean_word)
            if len(split_pieces) > 1:
                prefix = re.match(r'^([^\w]*)', token).group(1)
                suffix = re.search(r'([^\w]*)$', token).group(1)
                
                reconstructed = " ".join(split_pieces)
                final_tokens.append(f"{prefix}{reconstructed}{suffix}")
                continue
                
        final_tokens.append(token)

    return " ".join(final_tokens)

def convert_markdown_to_html(md_text):
    """Converts inline markdown text tags to standard XHTML tags."""
    html = md_text
    html = re.sub(r'\*\*\*(.*?)\*\*\*', r'<strong><em></em></strong>', html)
    html = re.sub(r'\*\*(.*?)\*\*', r'<strong></strong>', html)
    html = re.sub(r'\*(.*?)\*', r'<em></em>', html)
    paragraphs = html.split('
')
    return "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())

def convert_markdown_to_rtf(md_text):
    """Translates inline markdown layout nodes into explicit RTF control code words."""
    rtf_body = md_text
    rtf_body = rtf_body.replace('{', '\{').replace('}', '\}')
    rtf_body = rtf_body.replace('
', '\par
')
    
    rtf_body = re.sub(r'\*\*\*(.*?)\*\*\*', r'\b\i \i0\b0', rtf_body)
    rtf_body = re.sub(r'\*\*(.*?)\*\*', r'\b \b0', rtf_body)
    rtf_body = re.sub(r'\*(.*?)\*', r'\i \i0', rtf_body)
    
    rtf_header = r'{
tf1nsi\deff0{onttbl{0swisscharset0 Arial;}}0s24 '
    return rtf_header + rtf_body + r'}'

def save_to_epub(cleaned_md, epub_output_path, title_name):
    book = epub.EpubBook()
    book.set_identifier(f"id_{title_name.lower().replace(' ', '_')}")
    book.set_title(title_name)
    book.set_language('en')

    xhtml_body = convert_markdown_to_html(cleaned_md)

    c1 = epub.EpubHtml(title='Content', file_name='content.xhtml', lang='en')
    c1.content = f"<html><body><h1>{title_name}</h1>{xhtml_body}</body></html>"
    book.add_item(c1)

    book.toc = (epub.Link('content.xhtml', 'Content', 'content'),)
    book.spine = ['nav', c1]
    book.add_item(epub.EpubNav())
    book.add_item(epub.EpubNcx())
    epub.write_epub(str(epub_output_path), book, {})

def main():
    parser = argparse.ArgumentParser(description="Extract styling from PDF or EPUB files and cleanly save to RTF and EPUB.")
    parser.add_argument("file_path", type=str, help="Path to the PDF or EPUB file.")
    args = parser.parse_args()
    file_path = Path(args.file_path)

    if not file_path.is_file():
        print(f"❌ Error: The file '{file_path}' does not exist.")
        return

    ext = file_path.suffix.lower()
    if ext not in ['.pdf', '.epub']:
        print(f"❌ Error: Unsupported file format '{ext}'. Please provide a .pdf or .epub file.")
        return

    print(f"⚙️ Processing {ext.upper()} file: {file_path.name}...")
    
    # --- STEP 1: Extract Styled Markdown ---
    if ext == '.pdf':
        markdown_text = extract_markdown_from_pdf(file_path)
    else:
        markdown_text = extract_markdown_from_epub(file_path)
        
    raw_output_path = file_path.with_name(f"{file_path.stem}_extracted.txt")
    with open(raw_output_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)
    print(f"📄 Success! Raw marked text saved to: {raw_output_path.name}")
    
    # --- STEP 2: Clean and Stitch Format Blocks ---
    print("🧹 Filtering gibberish while maintaining style properties...")
    cleaned_md = clean_markdown_artifacts(raw_output_path)
    
    # --- STEP 3: Output Rich Text Format (RTF) Document ---
    cleaned_rtf_path = file_path.with_name(f"{file_path.stem}_cleaned.rtf")
    rtf_content = convert_markdown_to_rtf(cleaned_md)
    with open(cleaned_rtf_path, "w", encoding="utf-8") as f:
        f.write(rtf_content)
    print(f"✨ Success! Rich Text file saved to: {cleaned_rtf_path.name}")

    # --- STEP 4: Output Standard Electronic Book Package (EPUB) ---
    print("📚 Packing styled markup into structural EPUB eBook container...")
    cleaned_epub_path = file_path.with_name(f"{file_path.stem}_cleaned.epub")
    save_to_epub(cleaned_md, cleaned_epub_path, title_name=file_path.stem.replace('_', ' ').title())
    print(f"📖 Success! Cleaned EPUB version saved to: {cleaned_epub_path.name}")

if __name__ == "__main__":
    main()
