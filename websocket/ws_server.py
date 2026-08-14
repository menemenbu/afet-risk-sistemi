"""
WebSocket Sunucusu
------------------
Gateway'in ürettiği bölge verilerini bağlı istemcilere (ileride
tarayıcıdaki Canlı Harita) gerçek zamanlı olarak yayınlar (broadcast).

Gateway, MQTT ile senkron (loop_forever) çalıştığı için, WebSocket
sunucusu ayrı bir thread'de kendi asyncio event loop'unu çalıştırır.
Gateway tarafında sadece `yayinla(mesaj)` fonksiyonu çağrılır -
senkron bir fonksiyon gibi kullanılır, arka planda mesajı asyncio
loop'una thread-safe şekilde iletir.
"""

import asyncio
import json
import threading

import websockets

# WS_HOST = "0.0.0.0": tüm ağ arayüzlerinden bağlantı kabul eder.
# Bu, hem yerel kullanımda (localhost dahil) hem Docker container
# içinde çalışırken (port yönlendirmesinin çalışabilmesi için "localhost"
# DEĞİL, 0.0.0.0 dinlenmelidir) doğru şekilde çalışır.
WS_HOST = "0.0.0.0"
WS_PORT = 8765

_baglantilar = set()
_loop = None  # WebSocket sunucusunun çalıştığı asyncio event loop
_mesaj_callback = None  # istemciden mesaj geldiğinde çağrılacak fonksiyon


def mesaj_dinleyicisi_ayarla(callback):
    """
    Gateway tarafından çağrılır. İstemciden (örn. Komuta Paneli) bir
    mesaj geldiğinde bu callback fonksiyonu çağrılır. callback,
    ayrıştırılmış (dict) mesajı parametre olarak alır.
    """
    global _mesaj_callback
    _mesaj_callback = callback


async def _handler(websocket):
    """Yeni bir istemci bağlandığında/ayrıldığında listeyi günceller,
    istemciden gelen mesajları dinler."""
    _baglantilar.add(websocket)
    print(f"[WebSocket] Yeni istemci bağlandı. Toplam: {len(_baglantilar)}")
    try:
        async for ham_mesaj in websocket:
            if _mesaj_callback is not None:
                try:
                    mesaj = json.loads(ham_mesaj)
                    _mesaj_callback(mesaj)
                except json.JSONDecodeError:
                    print("[WebSocket] Geçersiz JSON mesaj alındı, atlanıyor.")
    finally:
        _baglantilar.discard(websocket)
        print(f"[WebSocket] İstemci ayrıldı. Toplam: {len(_baglantilar)}")


async def _yayinla_async(mesaj: dict):
    if not _baglantilar:
        return
    veri = json.dumps(mesaj, ensure_ascii=False)
    for baglanti in list(_baglantilar):
        try:
            await baglanti.send(veri)
        except websockets.exceptions.ConnectionClosed:
            _baglantilar.discard(baglanti)


def yayinla(mesaj: dict):
    """
    Gateway tarafından çağrılacak senkron fonksiyon.
    Mesajı tüm bağlı WebSocket istemcilerine gönderir.
    """
    if _loop is None:
        return  # sunucu henüz hazır değil, mesaj atlanır
    asyncio.run_coroutine_threadsafe(_yayinla_async(mesaj), _loop)


def _sunucuyu_calistir():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    async def _baslat():
        async with websockets.serve(_handler, WS_HOST, WS_PORT):
            print(f"[WebSocket] Sunucu çalışıyor: ws://{WS_HOST}:{WS_PORT}")
            await asyncio.Future()  # sonsuza kadar açık kal

    _loop.run_until_complete(_baslat())


def baslat():
    """
    WebSocket sunucusunu ayrı bir arka plan thread'inde başlatır.
    Gateway'in ana MQTT döngüsünü bloklamaz.
    """
    thread = threading.Thread(target=_sunucuyu_calistir, daemon=True)
    thread.start()