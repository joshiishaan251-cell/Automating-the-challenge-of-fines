import re
import pathlib

def test_extract(names):
    for name in names:
        info = {}
        # Supports Russian 'Вручено' and English 'Delivered'
        date_match = re.search(r'(?:Delivered|Вручено)\s+(\d{2}\.\d{2}\.\d{4})', name, re.IGNORECASE)
        if not date_match:
            date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', name)
            
        rpo_match = re.search(r'(?:RPO|РПО)\s*(\d+)', name, re.IGNORECASE)
        
        if date_match:
            info["DataNumber"] = date_match.group(1)
        if rpo_match:
            info["PochtaNumber"] = rpo_match.group(1)
            
        print(f"File: {name} -> {info}")

test_extract([
    "Delivered 20.02.2026 IP Korotaev OA RPO 63097717173898",
    "Delivered 20.02.2026 IP Korotaev OA RPO 63097717173898.pdf",
    "Delivered  20.02.2026  RPO 123.pdf",
    "Something else 20.02.2026 RPO 123",
])
