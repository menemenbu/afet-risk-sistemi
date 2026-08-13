"""
Gerçek Zamanlı Veri Simülatörü
-------------------------------
Statik mock JSON dosyalarının yerine geçen, SÜREKLİ çalışan bir veri
kaynağı. Amaç: gerçek donanım bağlanana kadar, sistemin (Gateway,
YZ Motoru, Harita) canlı/kesintisiz veri akışı altında nasıl
davrandığını test edebilmek.

Tasarım kararı: Sensörler SABİT İSTASYONLAR olarak modellenir -
gerçek hayatta bir sismik sensör ya da drone konma istasyonu aynı
yerde durur, zamanla sadece OKUDUĞU DEĞER değişir. Bu yüzden her
istasyonun konumu sabittir; rastgele olan şey konum değil, ölçüm
değerleridir.

Gerçek donanıma geçiş: Bu dosyadaki `olcum_uret()` fonksiyonunu,
gerçek sensörden veri okuyan bir fonksiyonla değiştirmek yeterlidir.
Adaptör / MQTT / Gateway / YZ Motoru katmanlarının HİÇBİRİNİN
değişmesi gerekmez - çünkü hepsi aynı ortak JSON şemasını bekliyor.
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "adaptor"))
from adaptor import veri_dogrula, mqtt_baglan, gateway_gonder

# --- Sabit Sensör İstasyonları ---
# Gerçek bir sensör ağı kurulumunu taklit eder: her istasyon sabit bir
# yerde durur, sadece zamanla farklı ölçümler üretir.
# 5 farklı bölgeye dağıtılmıştır (birbirinden en az ~150-300m uzakta,
# Gateway'in KONUM_YARICAPI_METRE=100 değeriyle birleşmeyecek şekilde).
# Gerçekçi olması için her bölgede TÜM sensör tipleri bulunmuyor -
# bazı noktalarda kısmi kapsam var (gerçek sahada da böyle olurdu).

SENSOR_ISTASYONLARI = [
    # --- Bölge A: Tam kapsam (5 sensör tipi) ---
    {"sensor_id": "termal_drone_istasyon_a", "sensor_tipi": "termal",
     "konum": {"lat": 41.6773, "lon": 26.5557}},
    {"sensor_id": "kizilotesi_istasyon_a", "sensor_tipi": "kizilotesi",
     "konum": {"lat": 41.6774, "lon": 26.5558}},
    {"sensor_id": "ses_istasyon_a", "sensor_tipi": "ses",
     "konum": {"lat": 41.6772, "lon": 26.5556}},
    {"sensor_id": "rf_istasyon_a", "sensor_tipi": "rf",
     "konum": {"lat": 41.6771, "lon": 26.5554}},
    {"sensor_id": "sismik_istasyon_a", "sensor_tipi": "sismik",
     "konum": {"lat": 41.6770, "lon": 26.5553}},

    # --- Bölge B: Kısmi kapsam (termal + ses + sismik) ---
    {"sensor_id": "termal_drone_istasyon_b", "sensor_tipi": "termal",
     "konum": {"lat": 41.6850, "lon": 26.5610}},
    {"sensor_id": "ses_istasyon_b", "sensor_tipi": "ses",
     "konum": {"lat": 41.6851, "lon": 26.5611}},
    {"sensor_id": "sismik_istasyon_b", "sensor_tipi": "sismik",
     "konum": {"lat": 41.6849, "lon": 26.5609}},

    # --- Bölge C: Kısmi kapsam (kızılötesi + rf) ---
    {"sensor_id": "kizilotesi_istasyon_c", "sensor_tipi": "kizilotesi",
     "konum": {"lat": 41.6700, "lon": 26.5480}},
    {"sensor_id": "rf_istasyon_c", "sensor_tipi": "rf",
     "konum": {"lat": 41.6701, "lon": 26.5481}},

    # --- Bölge D: Tam kapsam (5 sensör tipi) ---
    {"sensor_id": "termal_drone_istasyon_d", "sensor_tipi": "termal",
     "konum": {"lat": 41.6920, "lon": 26.5700}},
    {"sensor_id": "kizilotesi_istasyon_d", "sensor_tipi": "kizilotesi",
     "konum": {"lat": 41.6921, "lon": 26.5701}},
    {"sensor_id": "ses_istasyon_d", "sensor_tipi": "ses",
     "konum": {"lat": 41.6919, "lon": 26.5699}},
    {"sensor_id": "rf_istasyon_d", "sensor_tipi": "rf",
     "konum": {"lat": 41.6922, "lon": 26.5702}},
    {"sensor_id": "sismik_istasyon_d", "sensor_tipi": "sismik",
     "konum": {"lat": 41.6918, "lon": 26.5698}},

    # --- Bölge E: Sadece sismik (tek başına yapısal risk odaklı nokta) ---
    {"sensor_id": "sismik_istasyon_e", "sensor_tipi": "sismik",
     "konum": {"lat": 41.6650, "lon": 26.5620}},
]

# Her tur (tick) arasında beklenecek süre (saniye)
TUR_ARALIGI_SANIYE = 5

# Bir istasyonun "pozitif sinyal" (örn. insan sesi/sıcaklığı tespit
# edilmiş gibi) üretme olasılığı - gerçekçi olması için düşük tutulur,
# çoğu ölçüm "normal/arka plan" değerler olur.
POZITIF_SINYAL_OLASILIGI = 0.15


def _zaman_damgasi() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def olcum_uret(istasyon: dict) -> dict:
    """
    Bir istasyon için tek bir ölçüm kaydı üretir.
    Küçük bir olasılıkla "pozitif sinyal" (hayat belirtisi / yapısal
    risk kanıtı), çoğunlukla "normal/arka plan" değer üretir.
    """
    tip = istasyon["sensor_tipi"]
    pozitif = random.random() < POZITIF_SINYAL_OLASILIGI

    if tip == "termal":
        sicaklik_max = round(random.uniform(35, 38), 1) if pozitif else round(random.uniform(18, 26), 1)
        veri = {"sicaklik_max": sicaklik_max, "sicaklik_ortalama": round(random.uniform(18, 24), 1)}

    elif tip == "kizilotesi":
        sicaklik = round(random.uniform(35, 38), 1) if pozitif else round(random.uniform(18, 27), 1)
        veri = {"sicaklik": sicaklik, "hareket_tespit": pozitif}

    elif tip == "ses":
        desibel = random.randint(40, 60) if pozitif else random.randint(10, 25)
        veri = {"desibel": desibel, "insan_sesi_tespit": pozitif}

    elif tip == "rf":
        sinyal_gucu = random.randint(-70, -50) if pozitif else random.randint(-105, -85)
        veri = {"sinyal_gucu": sinyal_gucu, "cihaz_tespit": pozitif}

    elif tip == "sismik":
        titresim_siddeti = round(random.uniform(3.0, 5.0), 1) if pozitif else round(random.uniform(0.1, 1.5), 1)
        veri = {"titresim_siddeti": titresim_siddeti, "sure_sn": random.randint(1, 15)}

    else:
        raise ValueError(f"Bilinmeyen sensör tipi: {tip}")

    return {
        "sensor_id": istasyon["sensor_id"],
        "sensor_tipi": tip,
        "konum": istasyon["konum"],
        "zaman_damgasi": _zaman_damgasi(),
        # Güven skoru, pozitif sinyal durumunda biraz daha yüksek olacak
        # şekilde rastgele üretilir (gerçekte net bir tespitin genelde
        # daha az gürültülü/daha güvenilir olması beklenir).
        "guven_skoru": round(random.uniform(0.65, 0.95) if pozitif else random.uniform(0.2, 0.6), 2),
        "veri": veri,
    }


def simulasyonu_baslat():
    print(f"Simülatör başlıyor - {len(SENSOR_ISTASYONLARI)} istasyon, "
          f"her {TUR_ARALIGI_SANIYE} saniyede bir tur.")
    print("Durdurmak için Ctrl+C.\n")

    client = mqtt_baglan()
    client.loop_start()

    try:
        tur = 0
        while True:
            tur += 1
            print(f"--- Tur {tur} ---")
            for istasyon in SENSOR_ISTASYONLARI:
                kayit = olcum_uret(istasyon)
                gecerli, hata = veri_dogrula(kayit)
                if gecerli:
                    gateway_gonder(client, kayit)
                else:
                    print(f"[HATA] {istasyon['sensor_id']}: {hata}")

            time.sleep(TUR_ARALIGI_SANIYE)
    except KeyboardInterrupt:
        print("\nSimülatör durduruldu.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    simulasyonu_baslat()