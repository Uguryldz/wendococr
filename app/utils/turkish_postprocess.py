"""
Türkçe OCR çıktısı post-processing.

OCR motorları (RapidOCR, Tesseract, PaddleOCR) Türkçe diacritikleri sıklıkla kaybeder:
  - ö → o, ü → u, ç → c, ş → s, ğ → g, İ → I, ı → i
  - Birleşik/bozuk Unicode karakterler
  - Yaygın OCR artefaktları (|, }, {, ~, `, vb.)

Bu modül:
  1. Unicode normalizasyonu (NFC — birleşik form)
  2. Yaygın OCR karakter hataları düzeltme
  3. Türkçe kelime bazlı diacritik restorasyon (sözlük tabanlı)
  4. OCR artefakt temizleme
"""

import re
import unicodedata


# ═══════════════════════════════════════════════════════════
# 1. UNICODE NORMALİZASYON
# ═══════════════════════════════════════════════════════════

def normalize_unicode(text: str) -> str:
    """
    NFC normalizasyonu: ayrık diacritik + temel karakter → birleşik karakter.
    Örnek: 'o' + '\u0308' (combining diaeresis) → 'ö'
    """
    return unicodedata.normalize("NFC", text)


# ═══════════════════════════════════════════════════════════
# 2. YAYGIN OCR KARAKTER HATALARI
# ═══════════════════════════════════════════════════════════

# Tek karakter düzeltmeleri (OCR'ın sistematik olarak yanlış okuduğu)
_CHAR_FIXES = {
    "\u0131\u0307": "i",       # ı + combining dot above → i (Türkçe'de anlamlı)
    "\u0049\u0307": "\u0130",  # I + combining dot above → İ
    "\u00b0": "°",             # degree sign normalizasyonu
    "\ufb01": "fi",            # fi ligature
    "\ufb02": "fl",            # fl ligature
    "\u2018": "'",             # left single quote → apostrophe
    "\u2019": "'",             # right single quote → apostrophe
    "\u201c": '"',             # left double quote
    "\u201d": '"',             # right double quote
    "\u2013": "-",             # en dash
    "\u2014": "-",             # em dash
    "\u00a0": " ",             # non-breaking space → regular space
}

# Regex: ardışık combining marks temizle (OCR bazen fazladan ekler)
_EXTRA_COMBINING_RE = re.compile(r"([\u0300-\u036f]{2,})")


# Cok dilli OCR modeli (RapidOCR PP-OCRv6) Latin-disi karakter sizdirir.
# Turkce'de olmayan benzer gorunumlu harfleri dogru Turkce karsiligina cevir.
_LATIN_LEAK_FIXES = {
    "\u0219": "\u015f", "\u0218": "\u015e",  # s,S Romence virgullu -> s,S
    "\u010d": "\u011f", "\u010c": "\u011e",  # c,C Slav hacek -> g,G
    "\u0161": "\u015f", "\u0160": "\u015e",  # s,S Slav hacek s -> s,S
    "\u00cd": "\u0130", "\u00ed": "i",        # I,i akut -> I,i
    "\u00e4": "a", "\u00c4": "A",
    "\u00f3": "o", "\u00d3": "O",
    "\u00e9": "e", "\u00c9": "E",
    "\u016b": "u", "\u016a": "U",
    "\u00fa": "u", "\u00da": "U",
    "\u017c": "z", "\u017b": "Z",
}

# Latin-disi / Turkce'de hic bulunmayan sizinti karakterleri (tamamen sil).
# CJK, tam-genislik, kutu, ust-simge. ASCII ve mesru isaretlere dokunmaz.
_LEAKAGE_RE = re.compile(
    "[\u4e00-\u9fff"   # CJK ideograflar
    "\u3000-\u303f"    # CJK noktalama
    "\uff00-\uffef"    # tam-genislik (fullwidth)
    "\u25a0-\u25ff"    # geometrik sekiller (kutu)
    "\u00b9\u00b2\u00b3]"  # ust-simge 1,2,3
)


def fix_ocr_chars(text: str) -> str:
    """Yaygın OCR karakter hatalarını düzeltir."""
    for old, new in _CHAR_FIXES.items():
        text = text.replace(old, new)
    # Cok dilli model sizintilarini Turkce karsiligina cevir, sonra sil
    for old, new in _LATIN_LEAK_FIXES.items():
        text = text.replace(old, new)
    text = _LEAKAGE_RE.sub("", text)
    # Birden fazla combining mark varsa sadece ilkini tut
    text = _EXTRA_COMBINING_RE.sub(lambda m: m.group(0)[0], text)
    return text


# ═══════════════════════════════════════════════════════════
# 3. TÜRKÇE KELİME BAZLI DİACRİTİK RESTORASYON
# ═══════════════════════════════════════════════════════════

# Yüksek frekanslı Türkçe kelimeler: diacritiksiz → doğru form.
# Sadece kesin eşleşmeler — yanlış pozitif riski düşük olanlar.
# Lowercase karşılaştırma yapılır, orijinal case korunur.
_TURKISH_WORD_MAP: dict[str, str] = {
    # ç düzeltmeleri
    "calisma": "çalışma", "calismasi": "çalışması", "cikan": "çıkan",
    "cikis": "çıkış", "cikti": "çıktı", "cok": "çok", "cogu": "çoğu",
    "cogul": "çoğul", "cozum": "çözüm", "cozumleri": "çözümleri",
    "cevre": "çevre", "cocuk": "çocuk", "cocuklar": "çocuklar",
    # ğ düzeltmeleri
    "dogru": "doğru", "degil": "değil", "deger": "değer", "degisik": "değişik",
    "degisen": "değişen", "degistir": "değiştir", "ogrenci": "öğrenci",
    "ogretmen": "öğretmen", "yaklasik": "yaklaşık", "gosterge": "gösterge",
    # ı düzeltmeleri (i → ı gereken yerler)
    "acik": "açık", "acilis": "açılış", "alti": "altı", "asiri": "aşırı",
    "baslik": "başlık", "bilgi": "bilgi", "bir": "bir", "birinci": "birinci",
    "cikar": "çıkar", "giris": "giriş",
    # İ düzeltmeleri
    "ilk": "ilk", "ise": "ise", "iki": "iki", "icin": "için", "icerik": "içerik",
    "islem": "işlem", "istanbul": "İstanbul",
    # ö düzeltmeleri
    "on": "ön", "once": "önce", "onemli": "önemli", "ornek": "örnek",
    "ozet": "özet", "ozel": "özel", "odeme": "ödeme", "odenmis": "ödenmiş",
    # ş düzeltmeleri
    "basari": "başarı", "baslangic": "başlangıç", "dis": "dış",
    "disinda": "dışında", "ise": "işe", "islem": "işlem",
    "islemleri": "işlemleri", "sifre": "şifre", "sirket": "şirket",
    "sirketleri": "şirketleri",
    # ü düzeltmeleri
    "urun": "ürün", "urunler": "ürünler", "ucret": "ücret",
    "ucretsiz": "ücretsiz", "uye": "üye", "uyelik": "üyelik",
    "ustunde": "üstünde", "uzere": "üzere",
    # Finans/Findeks terimleri
    "borc": "borç", "borclar": "borçlar", "borclu": "borçlu",
    "gelecek": "gelecek", "gecikme": "gecikme", "gecikmis": "gecikmiş",
    "gecikmede": "gecikmede", "hesap": "hesap",
    "kredi": "kredi", "krediler": "krediler",
    "limit": "limit", "nakdi": "nakdi", "gayrinakdi": "gayrinakdi",
    "odenmemis": "ödenmemiş", "rapor": "rapor",
    "takip": "takip", "takibe": "takibe", "toplam": "toplam",
    "tutar": "tutar", "vade": "vade", "vadeli": "vadeli",
    # Banka isimleri (OCR'da sık bozulan)
    "turkiye": "Türkiye", "vakifbank": "VakıfBank",
    "sekerbank": "Şekerbank", "finansbank": "Finansbank",
    "denizbank": "DenizBank", "kuveytturk": "Kuveyt Türk",
    "ziraat": "Ziraat", "halkbank": "Halkbank",
    "garanti": "Garanti", "isbank": "İşbank",
    # Yaygın fiiller/ekler
    "alinmis": "alınmış", "alinmistir": "alınmıştır",
    "basvuru": "başvuru", "basvurular": "başvurular",
    "bildirimde": "bildirimde", "bulunan": "bulunan",
    "donemi": "dönemi", "donemleri": "dönemleri",
    "goruntusu": "görüntüsü", "guncelleme": "güncelleme",
    "guncel": "güncel", "hazirlan": "hazırlan",
    "kurulus": "kuruluş", "kuruluslari": "kuruluşları",
    "musteri": "müşteri", "musteriler": "müşteriler",
    "olustur": "oluştur", "olusturma": "oluşturma",
    "sonuc": "sonuç", "sonuclari": "sonuçları",
    "surec": "süreç", "surecleri": "süreçleri",
    "taahhut": "taahhüt", "tarih": "tarih",
    "tutari": "tutarı", "unvan": "ünvan", "unvani": "ünvanı",
}

# Case-insensitive lookup tablosu (oluştur)
_WORD_LOOKUP: dict[str, str] = {}
for _ascii_form, _turkish_form in _TURKISH_WORD_MAP.items():
    _WORD_LOOKUP[_ascii_form.lower()] = _turkish_form


def _restore_case(original: str, replacement: str) -> str:
    """Orijinal kelimenin case pattern'ını replacement'a uygular."""
    if original.isupper():
        return replacement.upper()
    if original[0].isupper() and original[1:].islower():
        return replacement[0].upper() + replacement[1:]
    return replacement


_WORD_BOUNDARY_RE = re.compile(r'\b([A-Za-zÀ-ÿçÇğĞıİöÖşŞüÜ]+)\b')


def restore_turkish_diacritics(text: str) -> str:
    """
    Kelime bazlı Türkçe diacritik restorasyon.
    Sözlükteki ASCII formları doğru Türkçe formlarına çevirir.
    """
    def _replace_word(match):
        word = match.group(1)
        lower = word.lower()
        if lower in _WORD_LOOKUP:
            return _restore_case(word, _WORD_LOOKUP[lower])
        return word

    return _WORD_BOUNDARY_RE.sub(_replace_word, text)


# ═══════════════════════════════════════════════════════════
# 4. OCR ARTEFAKT TEMİZLEME
# ═══════════════════════════════════════════════════════════

# Satır başı/sonu artefaktları
_LEADING_ARTIFACT_RE = re.compile(r'^[|}{~`\\]{1,3}(?=\s|\w)', re.MULTILINE)
_TRAILING_ARTIFACT_RE = re.compile(r'[|}{~`\\]{1,3}$', re.MULTILINE)

# Kelime içi tekrarlanan boşluklar (OCR bazen harf arası boşluk ekler)
_MULTI_SPACE_RE = re.compile(r' {3,}')


def clean_ocr_artifacts(text: str) -> str:
    """OCR artefaktlarını temizler (yapısal metni bozmadan)."""
    text = _LEADING_ARTIFACT_RE.sub('', text)
    text = _TRAILING_ARTIFACT_RE.sub('', text)
    text = _MULTI_SPACE_RE.sub('  ', text)
    return text


# ═══════════════════════════════════════════════════════════
# 5. ANA POST-PROCESSING FONKSİYONU
# ═══════════════════════════════════════════════════════════

def postprocess_turkish(text: str) -> str:
    """
    Türkçe OCR çıktısına tam post-processing uygular.

    Sıra:
    1. Unicode NFC normalizasyonu
    2. Yaygın OCR karakter hataları düzeltme
    3. OCR artefakt temizleme
    4. Türkçe diacritik restorasyon (kelime bazlı)

    Bu fonksiyon herhangi bir OCR engine çıktısına güvenle uygulanabilir.
    """
    if not text:
        return text
    text = normalize_unicode(text)
    text = fix_ocr_chars(text)
    text = clean_ocr_artifacts(text)
    text = restore_turkish_diacritics(text)
    return text


def postprocess_turkish_blocks(text_blocks: list[dict]) -> list[dict]:
    """
    text_blocks listesindeki her bloğun 'text' alanına Türkçe post-processing uygular.
    Orijinal listeyi değiştirir ve döndürür.
    """
    for block in text_blocks:
        if "text" in block and block["text"]:
            block["text"] = postprocess_turkish(block["text"])
    return text_blocks
