"""
pytest Ortak Yapılandırması
----------------------------
Bu dosya, testlerin proje modüllerini (adaptor, db, ai_engine, gateway,
websocket) import edebilmesi için gerekli yolları sys.path'e ekler.
pytest, testleri çalıştırmadan önce bu dosyayı otomatik olarak bulur
ve çalıştırır - başka hiçbir yerde import etmene gerek yok.
"""

import os
import sys

_KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for _klasor in ["adaptor", "db", "ai_engine", "gateway", "websocket", "simulator"]:
    sys.path.insert(0, os.path.join(_KOK, _klasor))