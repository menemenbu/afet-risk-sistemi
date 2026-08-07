"""
Merkezi Gateway Servisi
------------------------
Bu servis, tüm adaptörlerin "sensor/#" topic'lerine yayınladığı
verileri dinler ve şu işlemleri uygular:

1. Mesaj Dinleme    : MQTT broker'a abone olur, gelen her kaydı toplar.
2. Konum Eşleştirme : Birbirine yakın (aynı "bölge" sayılabilecek)
                       kayıtları gruplar.
3. Zaman Senkronu   : Aynı bölgedeki kayıtları belirli bir zaman
                       penceresi içinde eşleştirir.
4. Çakışma Çözümü   : Aynı bölge + zaman penceresinde birden fazla
                       sensörden veri geldiyse, güven skoruna göre
                       ağırlıklı bir "birleşik bölge kaydı" üretir.

Çıktısı, bir sonraki aşamada (YZ Motoru) risk skoru hesaplamak için
kullanılacak "birleşik bölge" listesidir.
"""

import json
import math
import time
import os
import sys
from datetime import datetime

import paho.mqtt.client as mqtt

# db/ ve ai_engine/ klasörlerindeki modülleri import edebilmek için yol ekle
_mevcut_klasor = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_mevcut_klasor, "..", "db"))
sys.path.insert(0, os.path.join(_mevcut_klasor, "..", "ai_engine"))
from database import Veritabani
from risk_motoru import bolge_risk_hesapla

# --- MQTT Ayarları ---
MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "sensor/#"   # tüm sensör tiplerini dinle

# --- Veritabanı Ayarı ---
DB_DOSYA_YOLU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "afet_risk.db")

# --- Konum Eşleştirme Ayarı ---
# Bu yarıçap içindeki kayıtlar "aynı bölge" sayılır.
KONUM_YARICAPI_METRE = 100

# --- Zaman Senkronu Ayarı ---
# Bu pencere içindeki kayıtlar "aynı zaman dilimi" sayılır.
ZAMAN_PENCERESI_SANIYE = 600  # 10 dakika


def haversine_metre(lat1, lon1, lat2, lon2) -> float:
    """
    İki GPS koordinatı arasındaki mesafeyi metre cinsinden hesaplar
    (Haversine formülü - Dünya'nın küresel yapısını dikkate alır).
    """
    R = 6371000  # Dünya yarıçapı (metre)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def zaman_farki_saniye(zaman1: str, zaman2: str) -> float:
    """İki ISO 8601 zaman damgası arasındaki farkı saniye cinsinden döner."""
    t1 = datetime.fromisoformat(zaman1.replace("Z", "+00:00"))
    t2 = datetime.fromisoformat(zaman2.replace("Z", "+00:00"))
    return abs((t1 - t2).total_seconds())


class BolgeHavuzu:
    """
    Gelen tüm sensör kayıtlarını tutar ve konum + zamana göre
    bölgelere gruplayarak "birleşik bölge" listesi üretir.

    Bir Veritabani nesnesi verilirse, her kayıt kalıcı olarak
    ham_kayitlar tablosuna yazılır ve hesaplanan bölgeler de
    bolgeler tablosuna kaydedilir.
    """

    def __init__(self, veritabani: "Veritabani | None" = None):
        self.kayitlar = []       # şimdiye kadar gelen tüm ham kayıtlar
        self.kayit_id_haritasi = {}  # id(kayit) -> veritabanındaki satır id'si
        self.vt = veritabani

    def ekle(self, kayit: dict):
        self.kayitlar.append(kayit)
        if self.vt is not None:
            db_id = self.vt.ham_kayit_ekle(kayit)
            self.kayit_id_haritasi[id(kayit)] = db_id

    def bolgele(self) -> list[dict]:
        """
        Kayıtları konum + zamana göre gruplar (basit bir kümeleme).
        Her kayıt, ilk uygun gruba eklenir; hiçbir gruba uymuyorsa
        yeni bir grup açılır.

        Döndürdüğü her grup şu bilgileri içerir:
        - merkez_konum: gruptaki ilk kaydın konumu (referans nokta)
        - kayitlar: gruba giren ham kayıtlar
        - sensor_tipleri: gruba katkı veren farklı sensör tipleri
        - birlesik_guven_skoru: güven skorlarının ağırlıklı ortalaması
        """
        gruplar = []

        for kayit in self.kayitlar:
            uygun_grup = None

            for grup in gruplar:
                mesafe = haversine_metre(
                    kayit["konum"]["lat"], kayit["konum"]["lon"],
                    grup["merkez_konum"]["lat"], grup["merkez_konum"]["lon"]
                )
                zaman_farki = zaman_farki_saniye(
                    kayit["zaman_damgasi"], grup["referans_zaman"]
                )

                if mesafe <= KONUM_YARICAPI_METRE and zaman_farki <= ZAMAN_PENCERESI_SANIYE:
                    uygun_grup = grup
                    break

            if uygun_grup is None:
                # Yeni bölge/grup aç
                gruplar.append({
                    "merkez_konum": kayit["konum"],
                    "referans_zaman": kayit["zaman_damgasi"],
                    "kayitlar": [kayit],
                })
            else:
                uygun_grup["kayitlar"].append(kayit)

        # Her grup için çakışma çözümü uygula (birleşik güven skoru üret)
        birlesik_bolgeler = []
        for grup in gruplar:
            birlesik_bolgeler.append(self._grubu_birlestir(grup))

        return birlesik_bolgeler

    def _grubu_birlestir(self, grup: dict) -> dict:
        """
        Çakışma Çözümü: Bir gruptaki (aynı bölge/zaman) kayıtları,
        güven skoruna göre ağırlıklı birleştirerek tek bir "bölge özeti"
        üretir. Daha yüksek güven skorlu sensörler sonuca daha çok etki eder.
        """
        kayitlar = grup["kayitlar"]
        toplam_guven = sum(k["guven_skoru"] for k in kayitlar)

        # Ağırlıklı birleşik güven skoru (basit ortalama + katkı sayısı bonusu)
        # Not: birden fazla farklı sensör tipi aynı bölgeyi doğruluyorsa
        # bu daha güvenilir bir işaret sayılır, bu yüzden ortalamaya ek
        # olarak "kaç farklı sensör tipi katkı verdi" bilgisini de taşıyoruz.
        ortalama_guven = toplam_guven / len(kayitlar)
        sensor_tipleri = sorted(set(k["sensor_tipi"] for k in kayitlar))

        return {
            "merkez_konum": grup["merkez_konum"],
            "kayit_sayisi": len(kayitlar),
            "sensor_tipleri": sensor_tipleri,
            "farkli_sensor_tipi_sayisi": len(sensor_tipleri),
            "birlesik_guven_skoru": round(ortalama_guven, 3),
            "kayitlar": kayitlar,
        }

    def rapor_yazdir(self):
        """
        Şu anki bölge durumunu okunabilir şekilde konsola yazdırır.
        Her bölge için YZ Motoru'ndan öncelik_skoru ve yapisal_risk_skoru
        alınır. Veritabanı bağlıysa, güncel durum bolgeler tablosuna
        da yazılır (önce eskisini temizleyip yenisini yazarak günceller).
        """
        bolgeler = self.bolgele()

        # Her bölge için YZ Motoru skorlarını hesapla
        for bolge in bolgeler:
            risk_sonucu = bolge_risk_hesapla(bolge)
            bolge["oncelik_skoru"] = risk_sonucu["oncelik_skoru"]
            bolge["yapisal_risk_skoru"] = risk_sonucu["yapisal_risk_skoru"]
            bolge["aciklama"] = risk_sonucu["aciklama"]

        if self.vt is not None:
            self.vt.bolgeleri_temizle()
            for bolge in bolgeler:
                kayit_idleri = [
                    self.kayit_id_haritasi[id(k)] for k in bolge["kayitlar"]
                    if id(k) in self.kayit_id_haritasi
                ]
                self.vt.bolge_kaydet(
                    bolge, kayit_idleri,
                    oncelik_skoru=bolge["oncelik_skoru"],
                    yapisal_risk_skoru=bolge["yapisal_risk_skoru"],
                )

        print(f"\n{'=' * 60}")
        print(f"BÖLGE RAPORU  ({len(self.kayitlar)} ham kayıt -> {len(bolgeler)} bölge)")
        print(f"{'=' * 60}")

        for i, bolge in enumerate(sorted(
                bolgeler, key=lambda b: b["oncelik_skoru"], reverse=True), start=1):
            konum = bolge["merkez_konum"]
            print(f"\nBölge {i}: ({konum['lat']}, {konum['lon']})")
            print(f"  Katkı veren sensör tipleri : {', '.join(bolge['sensor_tipleri'])}")
            print(f"  Farklı sensör tipi sayısı  : {bolge['farkli_sensor_tipi_sayisi']}")
            print(f"  Toplam kayıt sayısı        : {bolge['kayit_sayisi']}")
            print(f"  Birleşik güven skoru       : {bolge['birlesik_guven_skoru']}")
            print(f"  >>> ÖNCELİK SKORU          : {bolge['oncelik_skoru']}")
            print(f"  >>> YAPISAL RİSK SKORU     : {bolge['yapisal_risk_skoru']}")
            if bolge["aciklama"]:
                print(f"  Açıklama:")
                for satir in bolge["aciklama"]:
                    print(f"    - {satir}")


# --- MQTT Callback Fonksiyonları ---

havuz = None  # gateway_baslat() içinde Veritabani ile birlikte oluşturulacak


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Broker'a bağlanıldı (kod: {reason_code}). '{MQTT_TOPIC}' dinleniyor...")
    client.subscribe(MQTT_TOPIC)


def on_message(client, userdata, msg):
    try:
        kayit = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        print(f"[HATA] Geçersiz JSON mesaj alındı: {msg.topic}")
        return

    havuz.ekle(kayit)
    print(f"[ALINDI <- {msg.topic}] {kayit['sensor_id']} "
          f"(güven: {kayit['guven_skoru']})")

    # Her yeni kayıttan sonra güncel bölge raporunu yazdır (+ veritabanına kaydet)
    havuz.rapor_yazdir()


def gateway_baslat():
    global havuz

    vt = Veritabani(DB_DOSYA_YOLU)
    havuz = BolgeHavuzu(veritabani=vt)
    print(f"Veritabanı hazır: {DB_DOSYA_YOLU}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT)
    print("Gateway servisi çalışıyor. Durdurmak için Ctrl+C.")
    client.loop_forever()


if __name__ == "__main__":
    try:
        gateway_baslat()
    except KeyboardInterrupt:
        print("\nGateway servisi durduruldu.")