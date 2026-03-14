"""Text normalization utilities for Arabic and English fuzzy matching."""

import re


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text for fuzzy matching."""
    # Remove diacritics (tashkeel)
    text = re.sub(
        r'[\u0610-\u061A\u064B-\u065F\u0670'
        r'\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]',
        '', text,
    )
    # Normalize alef variants to plain alef
    text = re.sub(r'[إأآا]', 'ا', text)
    # Normalize taa marbuta to haa
    text = text.replace('ة', 'ه')
    # Normalize yaa variants
    text = text.replace('ى', 'ي')
    # Remove tatweel (kashida)
    text = text.replace('\u0640', '')
    return text.strip()


def normalize_text(text: str, language: str = "en") -> str:
    """Normalize text based on language for fuzzy matching."""
    if language == "ar":
        return normalize_arabic(text)
    # English: lowercase, strip extra whitespace
    return re.sub(r'\s+', ' ', text.lower().strip())
