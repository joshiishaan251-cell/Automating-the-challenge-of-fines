import re
import pathlib

def test_extract(names):
    for name in names:
        info = {}
        date_match = re.search(r'Вручено\s+(\d{2}\.\d{2}\.\d{4})', name, re.IGNORECASE)
        if not date_match:
            date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', name)
            
        rpo_match = re.search(r'РПО\s*(\d+)', name, re.IGNORECASE)
        
        if date_match:
            info["DataNumber"] = date_match.group(1)
        if rpo_match:
            info["PochtaNumber"] = rpo_match.group(1)
            
        print(f"File: {name} -> {info}")

test_extract([
    "Вручено 20.02.2026 ИП Коротаев ОА РПО 63097717173898",
    "Вручено 20.02.2026 ИП Коротаев ОА РПО 63097717173898.pdf",
    "Вручено  20.02.2026  РПО 123.pdf",
    "Что-то другое 20.02.2026 РПО 123",
])
