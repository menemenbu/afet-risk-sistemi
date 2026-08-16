"""
Kontrol Sunucusu (Basit HTTP)
------------------------------
Komuta Paneli'ndeki "Simülatörü Başlat" butonunun, simülatör sürecini
Gateway ile AYNI ortamda (Docker container'ı içinde veya yerel
makinede Gateway'in çalıştığı yerde) tetikleyebilmesi için minimal
bir HTTP arayüzü sağlar. Kullanıcının ayrıca bir terminal açıp komut
çalıştırmasına gerek kalmaz - simülatör, Gateway'in bulunduğu ortamda
bir alt süreç (subprocess) olarak başlatılır.

Endpoint'ler:
  POST /simulator/baslat  -> simülatörü başlatır (zaten çalışıyorsa no-op)
  GET  /simulator/durum   -> {"calisiyor": true/false}

Güvenlik notu: Bu, sadece yerel geliştirme/demo amaçlıdır. Dışarıya
açık bir sunucuda "uzaktan process başlatma" uç noktası bırakmak
güvenlik riski oluşturur - üretim ortamında bu devre dışı bırakılmalı
veya kimlik doğrulamayla korunmalıdır.
"""

import http.server
import json
import os
import subprocess
import sys
import threading

CONTROL_PORT = 8766

_APP_KOKU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_simulator_sureci = None
_kilit = threading.Lock()


def _simulator_calisiyor_mu() -> bool:
    with _kilit:
        return _simulator_sureci is not None and _simulator_sureci.poll() is None


def _simulator_baslat() -> str:
    """Simülatörü bir alt süreç olarak başlatır. Döner: 'baslatildi' | 'zaten_calisiyor'"""
    global _simulator_sureci
    with _kilit:
        if _simulator_sureci is not None and _simulator_sureci.poll() is None:
            return "zaten_calisiyor"

        _simulator_sureci = subprocess.Popen(
            [sys.executable, "simulator/simulator.py"],
            cwd=_APP_KOKU,
        )
        return "baslatildi"


class _Handler(http.server.BaseHTTPRequestHandler):
    def _cors_basliklari_ekle(self):
        # Tarayıcı, farklı porttaki (8000) frontend'den bu sunucuya (8766)
        # istek atacağı için CORS izni gerekiyor.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_gonder(self, veri: dict, kod: int = 200):
        govde = json.dumps(veri, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self._cors_basliklari_ekle()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_basliklari_ekle()
        self.end_headers()

    def do_POST(self):
        if self.path == "/simulator/baslat":
            sonuc = _simulator_baslat()
            self._json_gonder({"durum": sonuc})
        else:
            self._json_gonder({"hata": "bilinmeyen uç nokta"}, kod=404)

    def do_GET(self):
        if self.path == "/simulator/durum":
            self._json_gonder({"calisiyor": _simulator_calisiyor_mu()})
        else:
            self._json_gonder({"hata": "bilinmeyen uç nokta"}, kod=404)

    def log_message(self, format, *args):
        pass  # http.server'ın varsayılan konsol loglarını sustur


def baslat():
    """Kontrol HTTP sunucusunu ayrı bir arka plan thread'inde başlatır."""
    sunucu = http.server.ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), _Handler)
    thread = threading.Thread(target=sunucu.serve_forever, daemon=True)
    thread.start()
    print(f"[Kontrol Sunucusu] Çalışıyor: http://0.0.0.0:{CONTROL_PORT}")