import argparse
from pathlib import Path
import re
import sys

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

def extract_markdown_from_pdf(pdf_path):
    """
    Opens a PDF and extracts text, preserving bold and italic styles 
    by inspecting PyMuPDF font flags and writing inline Markdown tags.
    """
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
            page_content = "\n".join(page_lines)
            extracted_text.append(f"--- Page {page_num} ---\n{page_content}")

    return "\n\n".join(extracted_text)

def is_header_or_footer(line):
    """Identifies common book artifacts like running headers and Roman numeral strings."""
    stripped = re.sub(r'\*+', '', line).strip().lower()
    if not stripped:
        return False
        
    if re.search(r'\b[ex•\[\s]*(?:x[vlcx]*|v[ix]*|i[vx]*)[ex•\]\s]*\b', stripped):
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
        if line.strip().startswith("--- Page"):
            cleaned_lines.append(line)
            continue
            
        if check_line_quality(line):
            cleaned_lines.append(line)

    full_text = "".join(cleaned_lines)
    full_text = re.sub(r'\n+--- Page \d+ ---\n+', r' ', full_text)

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
    html = re.sub(r'\*\*\*(.*?)\*\*\*', r'<strong><em>\1</em></strong>', html)
    html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.*?)\*', r'<em>\1</em>', html)
    paragraphs = html.split('\n')
    return "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())

def convert_markdown_to_rtf(md_text):
    """Translates inline markdown layout nodes into explicit RTF control code words."""
    rtf_body = md_text
    rtf_body = rtf_body.replace('{', '\\{').replace('}', '\\}')
    rtf_body = rtf_body.replace('\n', '\\par\n')
    
    rtf_body = re.sub(r'\*\*\*(.*?)\*\*\*', r'\\b\\i \1\\i0\\b0', rtf_body)
    rtf_body = re.sub(r'\*\*(.*?)\*\*', r'\\b \1\\b0', rtf_body)
    rtf_body = re.sub(r'\*(.*?)\*', r'\\i \\i0', rtf_body)
    
    rtf_header = r'{\rtf1\ansi\deff0{\fonttbl{\f0\fswiss\fcharset0 Arial;}}\f0\fs24 '
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
    parser = argparse.ArgumentParser(description="Extract styling from PDF and cleanly save to RTF and EPUB.")
    parser.add_argument("pdf_path", type=str, help="Path to the PDF file.")
    args = parser.parse_args()
    pdf_path = Path(args.pdf_path)

    if not pdf_path.is_file():
        print(f"❌ Error: The file '{pdf_path}' does not exist.")
        return

    print(f"⚙️ Processing with PyMuPDF: {pdf_path.name}...")
    
    # --- STEP 1: Extract Styled Markdown ---
    markdown_text = extract_markdown_from_pdf(pdf_path)
    raw_output_path = pdf_path.with_name(f"{pdf_path.stem}_extracted.txt")
    
    with open(raw_output_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)
    print(f"📄 Success! Raw marked text saved to: {raw_output_path.name}")
    
    # --- STEP 2: Clean and Stitch Format Blocks ---
    print("🧹 Filtering gibberish while maintaining style properties...")
    cleaned_md = clean_markdown_artifacts(raw_output_path)
    
    # --- STEP 3: Output Rich Text Format (RTF) Document ---
    cleaned_rtf_path = pdf_path.with_name(f"{pdf_path.stem}_cleaned.rtf")
    rtf_content = convert_markdown_to_rtf(cleaned_md)
    with open(cleaned_rtf_path, "w", encoding="utf-8") as f:
        f.write(rtf_content)
    print(f"✨ Success! Rich Text file saved to: {cleaned_rtf_path.name}")

    # --- STEP 4: Output Standard Electronic Book Package (EPUB) ---
    print("📚 Packing styled markup into structural EPUB eBook container...")
    cleaned_epub_path = pdf_path.with_name(f"{pdf_path.stem}_cleaned.epub")
    save_to_epub(cleaned_md, cleaned_epub_path, title_name=pdf_path.stem.replace('_', ' ').title())
    print(f"📖 Success! Cleaned EPUB version saved to: {cleaned_epub_path.name}")

if __name__ == "__main__":
    main()
