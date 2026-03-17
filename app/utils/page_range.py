"""Sayfa aralığı parse: '1-5', '1,3,7' -> 0-tabanlı indeks listesi."""
import re


def parse_page_range(s: str | None, max_pages: int = 9999) -> list[int] | None:
    """
    '1-5' -> [0,1,2,3,4]
    '1,3,7' -> [0,2,6]
    '1-3,7,9-10' -> [0,1,2,6,8,9]
    Boş/None -> None (tüm sayfalar)
    """
    if not s or not str(s).strip():
        return None
    s = str(s).strip()
    result: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            m = re.match(r"(\d+)\s*-\s*(\d+)", part)
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                for i in range(max(1, start), min(end, max_pages) + 1):
                    result.add(i - 1)  # 1-indexed -> 0-indexed
        else:
            try:
                n = int(part)
                if 1 <= n <= max_pages:
                    result.add(n - 1)
            except ValueError:
                pass
    if not result:
        return None
    return sorted(result)
