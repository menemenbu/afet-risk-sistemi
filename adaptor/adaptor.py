"""
Adaptör Modülü
--------------
Bu modül, her sensörden gelen (şimdilik mock/sabit) veriyi okur,
ortak veri şemasına uygunluğunu doğrular ve Merkezi Gateway'e
gönderime hazır hale getirir.

Şu an MQTT bağlantısı henüz kurulmadığı için `gateway_gonder()`
fonksiyonu bir "stub" (yer tutucu) - sadece konsola yazdırır.
İleride MQTT Broker aşamasında gerçek gönderim koduna çevrilecek.
"""

import json
import os
from datetime import datetime

# Ortak şemada zorunlu olan üst seviye alanlar
ZORUNLU_ALANLAR = ["sensor_id", "sensor_tipi", "konum", "zaman_damgasi", "guven_skoru", "veri"]

# Geçerli sensör tipleri
GECERLI_TIPLER = ["termal", "ses", "kizilotesi", "rf", "sismik"]

# Her sensör tipinin "veri" alanında olması gereken zorunlu anahtarlar
SENSOR_VERI_ALANLARI = {
    "termal": ["sicaklik_max", "sicaklik_ortalama"],
    "ses": ["desibel", "insan_sesi_tespit"],
    "kizilotesi": ["sicaklik", "hareket_tespit"],
    "rf": ["sinyal_gucu", "cihaz_tespit"],
    "sismik": ["titresim_siddeti", "sure_sn"],
}


def veri_dogrula(kayit: dict) -> tuple[bool, str]:
    """
    Tek bir sensör kaydının ortak şemaya uygun olup olmadığını kontrol eder.
    Geriye (gecerli_mi, hata_mesaji) döner.
    """
    # 1. Zorunlu üst seviye alanlar var mı?
    for alan in ZORUNLU_ALANLAR:
        if alan not in kayit:
            return False, f"Eksik alan: '{alan}'"

    # 2. sensor_tipi geçerli mi?
    tip = kayit["sensor_tipi"]
    if tip not in GECERLI_TIPLER:
        return False, f"Geçersiz sensor_tipi: '{tip}'"

    # 3. konum alanı doğru yapıda mı?
    konum = kayit["konum"]
    if not isinstance(konum, dict) or "lat" not in konum or "lon" not in konum:
        return False, "Konum alanı 'lat' ve 'lon' içermeli"

    # 4. guven_skoru 0-1 aralığında mı?
    skor = kayit["guven_skoru"]
    if not isinstance(skor, (int, float)) or not (0 <= skor <= 1):
        return False, f"guven_skoru 0-1 aralığında olmalı, gelen: {skor}"

    # 5. zaman_damgasi doğru formatta mı? (ISO 8601)
    try:
        datetime.fromisoformat(kayit["zaman_damgasi"].replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False, f"zaman_damgasi geçersiz format: {kayit['zaman_damgasi']}"

    # 6. Sensöre özel veri alanları eksiksiz mi?
    beklenen_alanlar = SENSOR_VERI_ALANLARI.get(tip, [])
    veri = kayit.get("veri", {})
    for alan in beklenen_alanlar:
        if alan not in veri:
            return False, f"'{tip}' için eksik veri alanı: '{alan}'"

    return True, ""


def gateway_gonder(kayit: dict):
    """
    Doğrulanmış veriyi Gateway'e gönderir.
    ŞİMDİLİK: Sadece konsola yazdırır (stub).
    SONRA: MQTT publish burada yapılacak, örn:
        mqtt_client.publish("sensor/veri", json.dumps(kayit))
    """
    print(f"[GÖNDERİLDİ] {kayit['sensor_id']} ({kayit['sensor_tipi']}) "
          f"-> güven: {kayit['guven_skoru']}, zaman: {kayit['zaman_damgasi']}")


def dosya_isle(dosya_yolu: str):
    """
    Bir mock veri dosyasını okur, her kaydı doğrular ve
    geçerli olanları Gateway'e gönderir. Geçersiz kayıtları raporlar.
    """
    with open(dosya_yolu, "r", encoding="utf-8") as f:
        kayitlar = json.load(f)

    print(f"\n=== İşleniyor: {os.path.basename(dosya_yolu)} ({len(kayitlar)} kayıt) ===")

    for i, kayit in enumerate(kayitlar, start=1):
        gecerli, hata = veri_dogrula(kayit)
        if gecerli:
            gateway_gonder(kayit)
        else:
            print(f"[HATA] Kayıt {i}: {hata}")


def tum_mock_verileri_isle(mock_klasoru: str):
    """
    mock-data klasöründeki tüm .json dosyalarını sırayla işler.
    """
    for dosya_adi in sorted(os.listdir(mock_klasoru)):
        if dosya_adi.endswith(".json"):
            dosya_isle(os.path.join(mock_klasoru, dosya_adi))


if __name__ == "__main__":
    # Bu script'in bulunduğu klasöre göre mock-data klasörünü bul
    mevcut_klasor = os.path.dirname(os.path.abspath(__file__))
    mock_klasoru = os.path.join(mevcut_klasor, "..", "mock_data")

    tum_mock_verileri_isle(mock_klasoru)