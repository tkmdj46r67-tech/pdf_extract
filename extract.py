import argparse
from pathlib import Path
import re
import sys

# --- DEPENDENCY CHECKING BLOCK ---
REQUIRED_PACKAGES = {
    "pdfplumber": "pip install pdfplumber",
    "nltk": "pip install nltk",
    "wordninja": "pip install wordninja",
    "ebooklib": "pip install ebooklib"
}

missing_packages = []
for package in REQUIRED_PACKAGES:
    try:
        __import__(package)
    except ImportError:
        missing_packages.append(package)

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

# Safely import dependencies now that we verified they exist
import ssl
import pdfplumber
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

def extract_text_from_pdf(pdf_path):
    """Opens a PDF and returns the extracted text from all pages."""
    extracted_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if text:
                extracted_text.append(f"--- Page {page_num} ---\n{text}")
    return "\n\n".join(extracted_text)

def is_header_or_footer(line):
    """Identifies common book artifacts like running headers and Roman numeral strings."""
    stripped = line.strip().lower()
    if not stripped:
        return False
        
    # Pattern 1: Roman numerals wrapped in symbols/letters (e.g., eXIVe, •xiv•, [xiv])
    if re.search(r'\b[ex•\[\s]*(?:x[vlcx]*|v[ix]*|i[vx]*)[ex•\]\s]*\b', stripped):
        if any(term in stripped for term in ["castxe", "castle", "dick", "life", "high", "purr", "philip"]):
            return True
            
    # Pattern 2: Lines that are strictly numbers or page indicators
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
    stripped = line.strip()
    if not stripped:
        return False

    if is_header_or_footer(line):
        return False

    total_chars = len(stripped)
    alnum_chars = len([c for c in stripped if c.isalnum() or c.isspace()])
    punct_ratio = (total_chars - alnum_chars) / total_chars
    if punct_ratio > max_punctuation_ratio:
        return False

    alpha_only = "".join([c for c in stripped if c.isalpha()]).lower()
    if len(alpha_only) > 3:
        vowels = len(re.findall(r'[aeiouy]', alpha_only))
        if vowels == 0 or (len(alpha_only) - vowels) == 0:
            return False

    tokens = stripped.split()
    if not tokens:
        return False
        
    valid_count = sum(1 for token in tokens if is_valid_word(token))
    real_word_ratio = valid_count / len(tokens)
    
    return real_word_ratio >= min_real_word_ratio

def clean_gibberish_from_file(input_txt_path):
    """Reads a raw text file line-by-line, filters out heavy garbage, and returns cleaned string."""
    cleaned_lines = []
    
    with open(input_txt_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line in lines:
        if line.strip().startswith("--- Page"):
            cleaned_lines.append(line)
            continue
            
        words_in_line = line.split()
        filtered_words = []
        for w in words_in_line:
            if len(w) > 1 and not re.sub(r'[^\w]', '', w):
                continue
            filtered_words.append(w)
            
        reconstructed_line = " ".join(filtered_words) + "\n"
        
        if check_line_quality(reconstructed_line):
            cleaned_lines.append(reconstructed_line)

    full_text = "".join(cleaned_lines)
    full_text = re.sub(r'\n+--- Page \d+ ---\n+', r' ', full_text)

    # --- ADVANCED SPELLCHECK-SPLITTING LOOP ---
    final_words = []
    for word in full_text.split():
        clean_word = re.sub(r'[^\w]', '', word)
        
        if len(clean_word) > 4 and clean_word.isalpha() and clean_word.lower() not in ENGLISH_WORDS:
            split_pieces = wordninja.split(clean_word)
            if len(split_pieces) > 1:
                final_words.extend(split_pieces)
                continue
                
        final_words.append(word)

    return " ".join(final_words)

def save_to_epub(text_content, epub_output_path, title_name):
    """Wraps text strings into a valid, standard e-book document structure."""
    book = epub.EpubBook()

    # Set metadata identifiers
    book.set_identifier(f"id_{title_name.lower().replace(' ', '_')}")
    book.set_title(title_name)
    book.set_language('en')

    # Convert text newlines into XHTML paragraph tags for standard e-reader flow
    paragraphs = text_content.split('\n')
    xhtml_body = "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())

    # Create primary chapter entry
    c1 = epub.EpubHtml(title='Content', file_name='content.xhtml', lang='en')
    c1.content = f"<html><body><h1>{title_name}</h1>{xhtml_body}</body></html>"
    book.add_item(c1)

    # Define simple internal reading progression model
    book.toc = (epub.Link('content.xhtml', 'Content', 'content'),)
    book.spine = ['nav', c1]
    book.add_item(epub.EpubNav())
    book.add_item(epub.EpubNcx())

    # Finalize compression package output
    epub.write_epub(str(epub_output_path), book, {})

def main():
    parser = argparse.ArgumentParser(description="Extract, clean, and output text from a PDF file to TXT and EPUB.")
    parser.add_argument("pdf_path", type=str, help="Path to the PDF file.")
    args = parser.parse_args()
    pdf_path = Path(args.pdf_path)

    if not pdf_path.is_file():
        print(f"❌ Error: The file '{pdf_path}' does not exist.")
        return

    print(f"⚙️ Processing: {pdf_path.name}...")
    
    # --- STEP 1: Extract ---
    full_text = extract_text_from_pdf(pdf_path)
    raw_output_path = pdf_path.with_name(f"{pdf_path.stem}_extracted.txt")
    with open(raw_output_path, "w", encoding="utf-8") as f:
        f.write(full_text)
    print(f"📄 Success! Raw text saved to: {raw_output_path.name}")
    
    # --- STEP 2: Strict Clean ---
    print("¼🧹 Performing strict dictionary filtering and automatic word repair...")
    cleaned_text = clean_gibberish_from_file(raw_output_path)
    
    # Save the Cleaned TXT File
    cleaned_txt_path = pdf_path.with_name(f"{pdf_path.stem}_cleaned.txt")
    with open(cleaned_txt_path, 'w', encoding='utf-8') as f:
        f.write(cleaned_text)
    print(f"✨ Success! Deep-cleaned text saved to: {cleaned_txt_path.name}")

    # --- STEP 3: Convert to EPUB ---
    print("📚 Packing cleaned text into EPUB eBook structure...")
    cleaned_epub_path = pdf_path.with_name(f"{pdf_path.stem}_cleaned.epub")
    save_to_epub(cleaned_text, cleaned_epub_path, title_name=pdf_path.stem.replace('_', ' ').title())
    print(f"📖 Success! Cleaned EPUB version saved to: {cleaned_epub_path.name}")

if __name__ == "__main__":
    main()
