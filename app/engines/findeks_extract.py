"""
Findeks Risk Raporu PDF Extractor - Yapısal Veri Çıkarımı Engine.

Findeks Kredi Notu ve Risk Raporu PDF'lerinden tüm bölümleri yapısal olarak çıkarır.
JSON dict ve Excel (bytes) olarak export eder.

Bölümler:
  1. Rapor Özeti
  2. Ticari Krediler Özet
  3. Kredi Türü Bazında Hesap Bilgileri
  4. Vade Bazlı Limit ve Borç Bilgileri
  5. Bankalar Özet
  6. Banka Bazlı Limit/Risk Tablosu (OCR)
  7. Finansman Şirketleri Özet
  8. Finansman Şirketi Bazlı Limit/Risk Tablosu (OCR)
  9. Limit/Risk Tablosu Toplam
 10. Leasing
 11. Faktoring
 12. Takibe Alınmış Ticari Krediler
 13. Takibe Alınmış Krediler (Leasing)
 14. Takibe Alınmış Krediler (Faktoring)

**Kilitli modül** — düzgün çalışıyor, değiştirmeyin.
"""

import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageEnhance
import pytesseract
import io
import re
import unicodedata
import logging
from pathlib import Path
from difflib import SequenceMatcher

logger = logging.getLogger("wendococr.findeks_extract")


# ═══════════════════════════════════════════════════════════
# BANKA TANIMLAMA (OCR + Fuzzy Match)
# ═══════════════════════════════════════════════════════════

KNOWN_BANKS = [
    "Ziraat Bankası", "Türkiye İş Bankası", "VakıfBank", "Yapı Kredi",
    "Akbank", "Türkiye Finans", "Garanti BBVA", "Anadolubank",
    "Şekerbank", "Fibabanka", "QNB Finansbank", "Ziraat Katılım",
    "Kuveyt Türk", "Emlak Katılım", "ICBC Turkey", "ING Bank",
    "Vakıf Katılım", "Halkbank", "HSBC", "DenizBank", "Odeabank",
    "Alternatifbank", "TEB", "Burgan Bank", "Albaraka Türk",
    "Mercedes-Benz Finansal Hizmetler", "TEB Cetelem",
    "Volkswagen Doğuş Finans", "Aktif Bank",
]

BANK_ALIASES = {
    "ziraat bankasi": "Ziraat Bankası",
    "ziraat bankası": "Ziraat Bankası",
    "türkiye bankasi": "Türkiye İş Bankası",
    "türkiye $ bankasi": "Türkiye İş Bankası",
    "türkiye is bankasi": "Türkiye İş Bankası",
    "is bankasi": "Türkiye İş Bankası",
    "vakifbank": "VakıfBank",
    "vakıfbank": "VakıfBank",
    "yapikredi": "Yapı Kredi",
    "yapıkredi": "Yapı Kredi",
    "yapi kredi": "Yapı Kredi",
    "akbank": "Akbank",
    "türkiye finans": "Türkiye Finans",
    "turkiye finans": "Türkiye Finans",
    "garanti bbva": "Garanti BBVA",
    "anadolubank": "Anadolubank",
    "şekerbank": "Şekerbank",
    "sekerbank": "Şekerbank",
    "fibabanka": "Fibabanka",
    "qnb finansbank": "QNB Finansbank",
    "qnb": "QNB Finansbank",
    "ziraat katılım": "Ziraat Katılım",
    "ziraat katilim": "Ziraat Katılım",
    "kuveyt türk": "Kuveyt Türk",
    "kuveyttürk": "Kuveyt Türk",
    "kuveytturk": "Kuveyt Türk",
    "emlak katılım": "Emlak Katılım",
    "emlakkatılım": "Emlak Katılım",
    "emlakkatilim": "Emlak Katılım",
    "icbc": "ICBC Turkey",
    "ing": "ING Bank",
    "vakıf katılım": "Vakıf Katılım",
    "vakif katilim": "Vakıf Katılım",
    "halkbank": "Halkbank",
    "hsbc": "HSBC",
    "denizbank": "DenizBank",
    "odeabank": "Odeabank",
    "alternatifbank": "Alternatifbank",
    "alternatif bank": "Alternatifbank",
    "atternatit": "Alternatifbank",
    "atesi": "Alternatifbank",
    "teb": "TEB",
    "mercedes-benz finansal hizmetler": "Mercedes-Benz Finansal Hizmetler",
    "mercedes-benz": "Mercedes-Benz Finansal Hizmetler",
    "teb çetelem": "TEB Cetelem",
    "teb cetelem": "TEB Cetelem",
    "doğuş finans": "Volkswagen Doğuş Finans",
    "volkswagen doğuş finans": "Volkswagen Doğuş Finans",
    "volkswagen dogus finans": "Volkswagen Doğuş Finans",
    "arbank": "Akbank",
    "arbanr": "Akbank",
}


def normalize_turkish(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return text


def normalize_ocr(text: str) -> str:
    text = normalize_turkish(text)
    text = re.sub(r'^[\s\d#$@&*!?%^(){}[\]<>|/\\~`+=_\-.:;,\'"]+', '', text)
    text = re.sub(r'[\s\d#$@&*!?%^(){}[\]<>|/\\~`+=_\-.:;,\'"]+$', '', text)
    return text.strip()


def fuzzy_match_bank(ocr_text: str) -> tuple[str, float]:
    if not ocr_text:
        return ("TANINAMADI", 0.0)
    cleaned = normalize_ocr(ocr_text)
    lower = normalize_turkish(cleaned.lower())
    if not lower:
        return ("TANINAMADI", 0.0)

    for alias, name in BANK_ALIASES.items():
        norm_alias = normalize_turkish(alias)
        if norm_alias in lower:
            return (name, 1.0)
        if lower in norm_alias and len(lower) >= 3:
            return (name, 1.0)

    for bank in KNOWN_BANKS:
        for word in bank.lower().split():
            if len(word) > 3 and word in lower:
                return (bank, 0.85)

    best_score, best_match = 0.0, "TANINAMADI"
    for bank in KNOWN_BANKS:
        score = SequenceMatcher(None, lower, bank.lower()).ratio()
        if score > best_score:
            best_score, best_match = score, bank

    if best_score > 0.8:
        return (best_match, best_score)
    return (f"TANINAMADI ({cleaned})", 0.0)


def ocr_bank_image(doc, page, xref: int) -> str:
    candidates = []

    def try_ocr(img: Image.Image, label: str):
        for do_invert in [True, False]:
            proc = img.copy()
            if do_invert:
                proc = ImageOps.invert(proc.convert("RGB"))
            proc = ImageEnhance.Contrast(proc).enhance(2.0)
            gray = proc.convert("L")
            for thresh in [140, 120, 160]:
                binary = gray.point(lambda x, t=thresh: 0 if x < t else 255)
                for psm in [7, 6, 4, 8]:
                    text = pytesseract.image_to_string(
                        binary, lang='tur+eng', config=f'--psm {psm} --oem 3'
                    ).strip()
                    if text and len(text) > 1:
                        name, conf = fuzzy_match_bank(text)
                        candidates.append((name, conf))
                        if conf >= 0.85:
                            return
                if any(c[1] >= 0.85 for c in candidates):
                    return

    for alt_xref in [xref - 1, xref]:
        try:
            pix = fitz.Pixmap(doc, alt_xref)
            if pix.n > 4:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            w, h = img.size
            try_ocr(img.resize((w * 5, h * 5), Image.LANCZOS), f"xref{alt_xref}")
        except Exception:
            pass

    for rect in page.get_image_rects(xref):
        clip = fitz.Rect(55, rect.y0 - 8, 160, rect.y1 + 8)
        pix = page.get_pixmap(matrix=fitz.Matrix(8, 8), clip=clip)
        try_ocr(Image.open(io.BytesIO(pix.tobytes("png"))), "render")

    if candidates:
        recognized = [(n, c) for n, c in candidates if "TANINAMADI" not in n]
        if recognized:
            return max(recognized, key=lambda x: x[1])[0]
        return max(candidates, key=lambda x: x[1])[0]
    return "TANINAMADI"


# ═══════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════

def clean_page_text(text: str) -> list[str]:
    """Sayfa metninden footer/header satırlarını temizle."""
    lines = []
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            continue
        if s.startswith("Sayfa ") and len(s) < 10:
            continue
        if s == "RİSK RAPORU":
            continue
        if "FİRMA ÜNVANI" in s or "RAPOR TARİHİ" in s or "REFERANS NO" in s:
            continue
        if s.startswith("00**") or s.startswith("****"):
            continue
        if s == "02.02.2026" or s == "20298B1DDA8":
            continue
        if "Findeks Kredi Notu ve Risk Raporu" in s:
            break
        if "Kredi Kayıt Bürosu" in s:
            break
        lines.append(s)
    return lines


def parse_kv_pairs(lines: list[str]) -> dict:
    """Ardışık satırlardan etiket-değer çiftleri çıkar."""
    result = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            if re.match(r'^[\d.,/\-\s]+$', next_line) or next_line == '-':
                result[line] = next_line
                i += 2
                continue
        i += 1
    return result


# ═══════════════════════════════════════════════════════════
# BÖLÜM ÇIKARMA FONKSİYONLARI
# ═══════════════════════════════════════════════════════════

def extract_rapor_ozeti(doc) -> dict:
    """Sayfa 1 - Rapor özet bilgileri."""
    lines = clean_page_text(doc[0].get_text())
    result = {}
    for i, line in enumerate(lines):
        if "VERGİ NO" in line and i + 1 < len(lines):
            result["vergi_no"] = lines[i + 1]
        elif i > 0 and "VERGİ NO" in lines[i - 1]:
            pass
        elif "REFERANS KODU" in line and i + 1 < len(lines):
            result["referans_kodu"] = lines[i + 1]

    page1 = doc[0]
    text = page1.get_text()
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    for i, line in enumerate(raw_lines):
        if "FİRMA ÜNVANI" in line and "VERGİ" not in line and i + 1 < len(raw_lines):
            result["firma_unvani"] = raw_lines[i + 1]
        if "VERGİ NO" in line and i + 1 < len(raw_lines):
            result["vergi_no"] = raw_lines[i + 1]
        if "RAPOR TARİHİ" in line and i + 1 < len(raw_lines):
            result["rapor_tarihi"] = raw_lines[i + 1]
        if "REFERANS KODU" in line and i + 1 < len(raw_lines):
            result["referans_kodu"] = raw_lines[i + 1]
    return result


def extract_ticari_krediler_ozet(doc) -> dict:
    """Sayfa 2 - Ticari Krediler özet."""
    lines = clean_page_text(doc[1].get_text())
    result = {}

    kv_map = {
        "Bildirimde Bulunan Finans Kuruluşu Sayısı": "finans_kurulus_sayisi",
        "İlk Kredi Kullanım Tarihi": "ilk_kredi_tarihi",
        "Son Kredi Kullanım Tarihi": "son_kredi_tarihi",
        "Gecikmedeki Hesap Sayısı": "gecikmede_hesap_sayisi",
        "En Güncel Limit Tahsis Tarihi": "en_guncel_limit_tahsis_tarihi",
        "Gecikmedeki Borç Toplamı": "gecikmede_borc_toplami",
        "Takibe Alındığı Tarihteki Kredi Bakiyeleri": "takip_kredi_bakiyeleri",
    }

    for i, line in enumerate(lines):
        for key_part, field_name in kv_map.items():
            if key_part in line and i + 1 < len(lines):
                result[field_name] = lines[i + 1]
                break

    for i, line in enumerate(lines):
        if "Toplam Limit ve Borç" in line:
            if i + 1 < len(lines):
                result["toplam_limit"] = lines[i + 1]
            if i + 2 < len(lines):
                result["toplam_borc"] = lines[i + 2]
        elif "Toplam Nakdi" in line:
            if i + 1 < len(lines):
                result["toplam_nakdi_limit"] = lines[i + 1]
            if i + 2 < len(lines):
                result["toplam_nakdi_borc"] = lines[i + 2]
        elif "Toplam Gayrinakdi" in line:
            if i + 1 < len(lines):
                result["toplam_gayrinakdi_limit"] = lines[i + 1]
            if i + 2 < len(lines):
                result["toplam_gayrinakdi_borc"] = lines[i + 2]

    return result


def extract_kredi_turu_bazinda(doc) -> list[dict]:
    """Sayfa 3-4 - Kredi Türü Bazında Hesap Bilgileri."""
    records = []

    for page_idx in [2, 3]:
        if page_idx >= doc.page_count:
            break
        page = doc[page_idx]
        text = page.get_text()
        if "Kredi Türü Bazında" not in text:
            continue

        td = page.get_text("dict")
        all_lines = []
        for block in td["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    t = "".join([s["text"] for s in line["spans"]])
                    if t.strip():
                        all_lines.append({
                            "text": t.strip(),
                            "x": round(line["bbox"][0]),
                            "y": round(line["bbox"][1]),
                        })

        y_groups = {}
        for line in all_lines:
            if line["y"] < 180 or line["y"] > 750:
                continue
            y_key = round(line["y"] / 12) * 12
            if y_key not in y_groups:
                y_groups[y_key] = []
            y_groups[y_key].append(line)

        header_found = False
        current_type = None

        for y_key in sorted(y_groups.keys()):
            items = sorted(y_groups[y_key], key=lambda l: l["x"])
            texts = [i["text"] for i in items]

            if "Kredi Türü" in ' '.join(texts) or "Üye" in texts:
                header_found = True
                continue

            if not header_found:
                continue

            if len(items) == 1 and items[0]["x"] < 150:
                if current_type is None:
                    current_type = items[0]["text"]
                else:
                    current_type += " " + items[0]["text"]
                continue

            if items and len(items) >= 2:
                first_x = items[0]["x"]
                if first_x < 150:
                    name_parts = [items[0]["text"]]
                    if current_type:
                        name_parts = [current_type + " " + items[0]["text"]]
                    nums = [i["text"] for i in items if i["x"] > 150]
                    kredi_turu = ' '.join(name_parts)
                    current_type = None
                elif current_type:
                    kredi_turu = current_type
                    nums = [i["text"] for i in items]
                    current_type = None
                else:
                    continue

                if len(nums) >= 5:
                    records.append({
                        "kredi_turu": kredi_turu.strip(),
                        "uye_adedi": nums[0],
                        "acik_hesap_adedi": nums[1],
                        "kapali_hesap_adedi": nums[2],
                        "gecikme_tutari": nums[3],
                        "toplam_borc": nums[4],
                    })
                elif len(nums) >= 2:
                    records.append({
                        "kredi_turu": kredi_turu.strip(),
                        "uye_adedi": nums[0] if len(nums) > 0 else "-",
                        "acik_hesap_adedi": nums[1] if len(nums) > 1 else "-",
                        "kapali_hesap_adedi": nums[2] if len(nums) > 2 else "-",
                        "gecikme_tutari": nums[3] if len(nums) > 3 else "-",
                        "toplam_borc": nums[4] if len(nums) > 4 else "-",
                    })

    return records


def extract_vade_bazli(doc) -> list[dict]:
    """Sayfa 5 - Vade Bazlı Limit ve Borç Bilgileri."""
    records = []
    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        text = page.get_text()
        if "Vade Bazlı Limit ve Borç Bilgileri" not in text:
            continue

        td = page.get_text("dict")
        all_lines = []
        for block in td["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    t = "".join([s["text"] for s in line["spans"]])
                    if t.strip():
                        all_lines.append({
                            "text": t.strip(),
                            "x": round(line["bbox"][0]),
                            "y": round(line["bbox"][1]),
                        })

        y_groups = {}
        for line in all_lines:
            if line["y"] < 200 or line["y"] > 750:
                continue
            y_key = round(line["y"] / 11) * 11
            if y_key not in y_groups:
                y_groups[y_key] = []
            y_groups[y_key].append(line)

        current_category = None
        for y_key in sorted(y_groups.keys()):
            items = sorted(y_groups[y_key], key=lambda l: l["x"])
            texts = [i["text"] for i in items]

            if "Kategori" in texts or "Dönem" in texts:
                continue

            if len(items) == 1 and any(k in items[0]["text"] for k in ["SON 12 AY", "12+ AY", "24+ AY"]):
                current_category = items[0]["text"]
                continue

            if len(items) >= 4:
                records.append({
                    "kategori": current_category or "-",
                    "donem": texts[0],
                    "genel_limit": texts[1] if len(texts) > 1 else "-",
                    "nakdi_borc": texts[2] if len(texts) > 2 else "-",
                    "gayri_nakdi_borc": texts[3] if len(texts) > 3 else "-",
                })
        break

    return records


def extract_ozet_tablo(page) -> dict:
    """Bankalar/Finansman/Toplam Özet tablosunu çıkar."""
    td = page.get_text("dict")
    all_lines = []
    for block in td["blocks"]:
        if block["type"] == 0:
            for line in block["lines"]:
                t = "".join([s["text"] for s in line["spans"]])
                if t.strip():
                    all_lines.append({
                        "text": t.strip(),
                        "x": round(line["bbox"][0]),
                        "y": round(line["bbox"][1]),
                    })

    labels_limit = []
    values_limit = []
    labels_risk = []
    values_risk = []

    for line in sorted(all_lines, key=lambda l: (l["y"], l["x"])):
        if line["y"] < 180 or line["y"] > 750:
            continue
        x, text = line["x"], line["text"]
        if text in ["Limit (TL)", "RİSK (TL)", "TOPLAM"]:
            continue
        if x < 200:
            labels_limit.append(text)
        elif x < 340:
            values_limit.append(text)
        elif x < 420:
            labels_risk.append(text)
        else:
            values_risk.append(text)

    def merge(labels, values):
        result = {}
        merged = []
        i = 0
        while i < len(labels):
            label = labels[i]
            if label in ("Geciken", "Genel", "Gecikmiş", "En Büyük"):
                if i + 1 < len(labels):
                    label = label + " " + labels[i + 1]
                    i += 1
            merged.append(label)
            i += 1
        for j, lab in enumerate(merged):
            result[lab] = values[j] if j < len(values) else "-"
        return result

    return {
        "limit_tl": merge(labels_limit, values_limit),
        "risk_tl": merge(labels_risk, values_risk),
    }


def extract_banka_limit_risk(doc) -> tuple[list, list]:
    """Sayfa 7-14 Bankalar, Sayfa 16 Finansman - banka bazlı Limit/Risk."""
    all_banks = []
    all_finance = []

    for page_num in range(doc.page_count):
        page = doc[page_num]
        images = page.get_images(full=True)
        if not images:
            continue

        image_rects = []
        for img in images:
            xref = img[0]
            for r in page.get_image_rects(xref):
                image_rects.append((xref, r))
        if not image_rects:
            continue

        text = page.get_text()[:300]
        is_finance = "Finansman Şirketleri" in text

        td = page.get_text("dict")
        all_lines = []
        for block in td["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    t = "".join([s["text"] for s in line["spans"]])
                    if t.strip():
                        all_lines.append({
                            "text": t.strip(),
                            "x": round(line["bbox"][0]),
                            "y": round(line["bbox"][1]),
                        })

        sorted_rects = sorted(image_rects, key=lambda r: r[1].y0)

        for idx, (xref, rect) in enumerate(sorted_rects):
            bank_name = ocr_bank_image(doc, page, xref)

            y_start = rect.y0 - 70
            y_end = sorted_rects[idx + 1][1].y0 - 70 if idx + 1 < len(sorted_rects) else rect.y1 + 80

            block_lines = [
                l for l in all_lines
                if y_start <= l["y"] <= y_end and l["x"] >= 160 and l["y"] < 750
            ]

            labels_l, values_l, labels_r, values_r = [], [], [], []
            for line in sorted(block_lines, key=lambda l: (l["y"], l["x"])):
                x, t = line["x"], line["text"]
                if x < 200:
                    labels_l.append(t)
                elif x < 340:
                    values_l.append(t)
                elif x < 420:
                    labels_r.append(t)
                else:
                    values_r.append(t)

            def merge(labels, values):
                result = {}
                merged = []
                i = 0
                while i < len(labels):
                    lab = labels[i]
                    if lab in ("Geciken", "Genel", "Gecikmiş"):
                        if i + 1 < len(labels):
                            lab = lab + " " + labels[i + 1]
                            i += 1
                    merged.append(lab)
                    i += 1
                for j, lab in enumerate(merged):
                    result[lab] = values[j] if j < len(values) else "-"
                return result

            limit_data = merge(labels_l, values_l)
            risk_data = merge(labels_r, values_r)

            entry = {
                "kurulus_adi": bank_name,
                "limit_tl": {
                    "grup": limit_data.get("Grup", "-"),
                    "nakdi": limit_data.get("Nakdi", "-"),
                    "gayri_nakdi": limit_data.get("Gayri Nakdi", "-"),
                    "toplam": limit_data.get("Toplam", "-"),
                    "geciken_hesap_sayisi": limit_data.get("Geciken Hesap Sayısı", "-"),
                    "genel_revize_vadesi": limit_data.get("Genel Revize Vadesi", "-"),
                },
                "risk_tl": {
                    "grup": risk_data.get("Grup", "-"),
                    "nakdi": risk_data.get("Nakdi", "-"),
                    "gayri_nakdi": risk_data.get("Gayri Nakdi", "-"),
                    "toplam": risk_data.get("Toplam", "-"),
                    "gecikmis_tutar": risk_data.get("Gecikmiş Tutar", "-"),
                },
            }

            if is_finance:
                all_finance.append(entry)
            else:
                all_banks.append(entry)

    return all_banks, all_finance


def extract_leasing_faktoring(doc, keyword: str) -> dict:
    """Leasing/Faktoring bölümünü çıkar."""
    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        text = page.get_text()
        first_lines = clean_page_text(text)

        if not first_lines or keyword not in first_lines[0]:
            continue
        if "Takibe" in first_lines[0]:
            continue

        result = {}
        kv_map = {
            "Bildirim Dönemi": "bildirim_donemi",
            "Kredi Limiti": "kredi_limiti",
            "01-12 Ay Vadeli": "vade_01_12_ay",
            "12-24 Ay Vadeli": "vade_12_24_ay",
            "24+ Ay Vadeli": "vade_24_plus_ay",
            "Faiz Reeskont + Komisyon": "faiz_reeskont_komisyon",
            "Faiz Tahakkuku + Komisyon": "faiz_tahakkuk_komisyon",
            "Bildirimde Bulunan Finans Kuruluşları": "finans_kurulus_sayisi",
        }

        for i, line in enumerate(first_lines):
            for key_part, field_name in kv_map.items():
                if key_part in line and i + 1 < len(first_lines):
                    result[field_name] = first_lines[i + 1]
                    break

        return result

    return {}


def extract_takip_ticari(doc) -> dict:
    """Takibe Alınmış Ticari Krediler."""
    for page_idx in range(doc.page_count):
        text = doc[page_idx].get_text()
        lines = clean_page_text(text)
        if not lines or "Takibe Alınmış Ticari Krediler" not in lines[0]:
            continue

        result = {}
        kv_map = {
            "Bildirimde Bulunan Finans Kuruluşu Sayısı": "finans_kurulus_sayisi",
            "Takibe Alındığı Tarihteki Kredi Bakiyeleri": "takip_kredi_bakiyeleri",
            "Toplam Güncel Kredi Bakiyesi": "guncel_kredi_bakiyesi",
            "En Yakın Takibe Alınma Tarihi": "en_yakin_takip_tarihi",
            "En Son Takibe Alınma Tarihi": "en_son_takip_tarihi",
        }

        for i, line in enumerate(lines):
            for key_part, field_name in kv_map.items():
                if key_part in line and i + 1 < len(lines):
                    result[field_name] = lines[i + 1]
                    break
        return result

    return {}


def extract_takip_leasing_faktoring(doc, keyword: str) -> dict:
    """Takibe Alınmış Krediler (Leasing/Faktoring)."""
    for page_idx in range(doc.page_count):
        text = doc[page_idx].get_text()
        lines = clean_page_text(text)
        if not lines:
            continue
        if f"Takibe Alınmış Krediler ({keyword})" not in lines[0]:
            continue

        result = {}
        kv_map = {
            "Bildirim Dönemi": "bildirim_donemi",
            "Kredi Limiti": "kredi_limiti",
            "01-12 Ay Vadeli": "vade_01_12_ay",
            "12-24 Ay Vadeli": "vade_12_24_ay",
            "24+ Ay Vadeli": "vade_24_plus_ay",
            "Faiz Reeskont + Komisyon": "faiz_reeskont_komisyon",
            "Faiz Tahakkuku + Komisyon": "faiz_tahakkuk_komisyon",
            "Bildirimde Bulunan Finans Kuruluşları": "finans_kurulus_sayisi",
        }

        for i, line in enumerate(lines):
            for key_part, field_name in kv_map.items():
                if key_part in line and i + 1 < len(lines):
                    result[field_name] = lines[i + 1]
                    break
        return result

    return {}


# ═══════════════════════════════════════════════════════════
# ANA İŞLEM FONKSİYONLARI (API Engine)
# ═══════════════════════════════════════════════════════════

def process_findeks(pdf_path: str | Path) -> dict:
    """
    Findeks Risk Raporu PDF'ini işleyip yapısal dict döndürür.

    Returns:
        dict: Tüm bölümlerin yapısal verisi.
    """
    doc = fitz.open(str(pdf_path))
    logger.info("Findeks extract: %s (%d sayfa)", pdf_path, doc.page_count)

    rapor_ozeti = extract_rapor_ozeti(doc)
    ticari_ozet = extract_ticari_krediler_ozet(doc)
    kredi_turleri = extract_kredi_turu_bazinda(doc)
    vade_bazli = extract_vade_bazli(doc)

    bankalar_ozet = {}
    for page_idx in range(doc.page_count):
        text = doc[page_idx].get_text()
        if "Bankalar - Özet" in text[:200]:
            bankalar_ozet = extract_ozet_tablo(doc[page_idx])
            break

    bankalar, finansman = extract_banka_limit_risk(doc)

    finans_ozet = {}
    for page_idx in range(doc.page_count):
        text = doc[page_idx].get_text()
        if "Finansman Şirketleri - Özet" in text[:200]:
            finans_ozet = extract_ozet_tablo(doc[page_idx])
            break

    toplam_tablo = {}
    for page_idx in range(doc.page_count):
        text = doc[page_idx].get_text()
        if "Limit / Risk Tablosu - Toplam" in text[:200]:
            toplam_tablo = extract_ozet_tablo(doc[page_idx])
            break

    leasing = extract_leasing_faktoring(doc, "Leasing")
    faktoring = extract_leasing_faktoring(doc, "Faktoring")
    takip_ticari = extract_takip_ticari(doc)
    takip_leasing = extract_takip_leasing_faktoring(doc, "Leasing")
    takip_faktoring = extract_takip_leasing_faktoring(doc, "Faktoring")

    doc.close()

    logger.info(
        "Findeks extract tamamlandı: %d banka, %d finansman, %d kredi türü, %d vade dönemi",
        len(bankalar), len(finansman), len(kredi_turleri), len(vade_bazli),
    )

    return {
        "rapor_ozeti": rapor_ozeti,
        "ticari_krediler_ozet": ticari_ozet,
        "kredi_turu_bazinda_hesap_bilgileri": kredi_turleri,
        "vade_bazli_limit_borc": vade_bazli,
        "bankalar_ozet": bankalar_ozet,
        "banka_bazli_limit_risk": bankalar,
        "finansman_sirketleri_ozet": finans_ozet,
        "finansman_bazli_limit_risk": finansman,
        "limit_risk_toplam": toplam_tablo,
        "leasing": leasing,
        "faktoring": faktoring,
        "takibe_alinmis_ticari_krediler": takip_ticari,
        "takibe_alinmis_leasing": takip_leasing,
        "takibe_alinmis_faktoring": takip_faktoring,
    }


def generate_xlsx(data: dict) -> bytes:
    """
    Findeks extract verisinden Excel dosyası üretir.

    Returns:
        bytes: XLSX dosya içeriği.
    """
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        # Sheet 1: Rapor Özeti + Ticari Krediler Özet
        ozet_rows = [{"Alan": k, "Değer": v} for k, v in {**data.get("rapor_ozeti", {}), **data.get("ticari_krediler_ozet", {})}.items()]
        pd.DataFrame(ozet_rows).to_excel(writer, sheet_name="Rapor Özeti", index=False)

        # Sheet 2: Kredi Türü Bazında
        kredi_turleri = data.get("kredi_turu_bazinda_hesap_bilgileri", [])
        if kredi_turleri:
            pd.DataFrame(kredi_turleri).to_excel(writer, sheet_name="Kredi Türü Bazında", index=False)

        # Sheet 3: Vade Bazlı
        vade_bazli = data.get("vade_bazli_limit_borc", [])
        if vade_bazli:
            pd.DataFrame(vade_bazli).to_excel(writer, sheet_name="Vade Bazlı", index=False)

        # Sheet 4: Banka Limit/Risk
        bank_rows = []
        for entry in data.get("banka_bazli_limit_risk", []):
            bank_rows.append({
                "Kuruluş Tipi": "Banka",
                "Kuruluş Adı": entry["kurulus_adi"],
                "Limit - Grup": entry["limit_tl"]["grup"],
                "Limit - Nakdi": entry["limit_tl"]["nakdi"],
                "Limit - Gayri Nakdi": entry["limit_tl"]["gayri_nakdi"],
                "Limit - Toplam": entry["limit_tl"]["toplam"],
                "Geciken Hesap Sayısı": entry["limit_tl"]["geciken_hesap_sayisi"],
                "Genel Revize Vadesi": entry["limit_tl"]["genel_revize_vadesi"],
                "Risk - Grup": entry["risk_tl"]["grup"],
                "Risk - Nakdi": entry["risk_tl"]["nakdi"],
                "Risk - Gayri Nakdi": entry["risk_tl"]["gayri_nakdi"],
                "Risk - Toplam": entry["risk_tl"]["toplam"],
                "Gecikmiş Tutar": entry["risk_tl"]["gecikmis_tutar"],
            })
        for entry in data.get("finansman_bazli_limit_risk", []):
            bank_rows.append({
                "Kuruluş Tipi": "Finansman Şirketi",
                "Kuruluş Adı": entry["kurulus_adi"],
                "Limit - Grup": entry["limit_tl"]["grup"],
                "Limit - Nakdi": entry["limit_tl"]["nakdi"],
                "Limit - Gayri Nakdi": entry["limit_tl"]["gayri_nakdi"],
                "Limit - Toplam": entry["limit_tl"]["toplam"],
                "Geciken Hesap Sayısı": entry["limit_tl"]["geciken_hesap_sayisi"],
                "Genel Revize Vadesi": entry["limit_tl"]["genel_revize_vadesi"],
                "Risk - Grup": entry["risk_tl"]["grup"],
                "Risk - Nakdi": entry["risk_tl"]["nakdi"],
                "Risk - Gayri Nakdi": entry["risk_tl"]["gayri_nakdi"],
                "Risk - Toplam": entry["risk_tl"]["toplam"],
                "Gecikmiş Tutar": entry["risk_tl"]["gecikmis_tutar"],
            })
        if bank_rows:
            pd.DataFrame(bank_rows).to_excel(writer, sheet_name="Limit Risk Tablosu", index=False)

        # Sheet 5: Leasing + Faktoring + Takip
        diger_rows = []
        for label, key in [
            ("Leasing", "leasing"),
            ("Faktoring", "faktoring"),
            ("Takibe Alınmış Ticari Krediler", "takibe_alinmis_ticari_krediler"),
            ("Takibe Alınmış Leasing", "takibe_alinmis_leasing"),
            ("Takibe Alınmış Faktoring", "takibe_alinmis_faktoring"),
        ]:
            for k, v in data.get(key, {}).items():
                diger_rows.append({"Bölüm": label, "Alan": k, "Değer": v})
        if diger_rows:
            pd.DataFrame(diger_rows).to_excel(writer, sheet_name="Leasing Faktoring Takip", index=False)

    return buf.getvalue()
