"""
Gerçek Zamanlı Veri Simülatörü
-------------------------------
Statik mock JSON dosyalarının yerine geçen, SÜREKLİ çalışan bir veri
kaynağı. Amaç: gerçek donanım bağlanana kadar, sistemin (Gateway,
YZ Motoru, Harita) canlı/kesintisiz veri akışı altında nasıl
davrandığını test edebilmek.

--- Bu Simülatörün Temsil Ettiği Şey ---

Bu sensör ağı, çökmüş binalar altında hayat kurtarmak için kurulmuş
bir arama-kurtarma sistemini temsil eder. Gerçek bir enkaz alanında
tespit süreci NADİREN tek bir sensörün anlık kararıyla olur - tipik
akış şöyledir:

  1. Bir sensör (örn. termal drone) enkazda anormal bir sıcaklık fark
     eder - bu, "burada bir şey olabilir" şüphesidir, henüz kanıt değil.
  2. Ekip/sistem, o bölgeye diğer sensörleri (ses, kızılötesi, RF)
     yönlendirir veya zaten oradaki sensörler zamanla veri üretmeye
     devam eder. Birkaç ON SANİYE içinde bu sensörlerin bir kısmı da
     aynı bölgede pozitif okuma yapmaya başlar - yani DOĞRULAMA GECİKMELİ
     gelir, anlık değil.
  3. Bazı sensörler hiç doğrulama yapmayabilir (her sensör her şeyi
     yakalayamaz) - bu da gerçekçidir ve sistemin neden "kısmi
     doğrulanmış" bölgeleri de gösterebilmesi gerektiğinin sebebidir.

Bu dinamiği modellemek için olasılık artık SENSÖR BAŞINA değil,
BÖLGE BAŞINA bir "VAKA" (case) mekanizmasıyla yönetilir - bkz.
`_yeni_vaka_planla()` ve `_zonlari_guncelle()`.

--- Zaman İçindeki Genel Eğilim ---

1. BAŞLANGIÇ (hızlı): Yıkımın yoğun olduğu bölgelerde ilk taramada çok
   sayıda vaka açılır.
2. ORTA VADE (yavaşlama): Kolay bulunabilecek vakalar tükendikçe, yeni
   vaka açılma oranı azalır (üstel azalma, ama asla sıfıra inmez).
3. ARTÇI SARSINTI (belki yeniden hızlanma): Rastgele aralıklarla (garanti
   değil), enkaz hareket edip yeni vakaların açılma ihtimalini kısa süreliğine
   artırır; sismik sensörler artçıyı KESİN olarak algılar.

Gerçek donanıma geçiş: Bu dosyadaki `olcum_uret()` fonksiyonunu, gerçek
sensörden veri okuyan bir fonksiyonla değiştirmek yeterlidir. Adaptör /
MQTT / Gateway / YZ Motoru katmanlarının HİÇBİRİNİN değişmesi gerekmez -
hepsi aynı ortak JSON şemasını bekliyor.
"""

import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "adaptor"))
from adaptor import veri_dogrula, mqtt_baglan, gateway_gonder

# ============================================================
# 1. HASAR BÖLGELERİNİN OLUŞTURULMASI
# ============================================================
ZON_SAYISI = 9
MIN_ZON_MESAFESI_METRE = 250

BASE_LAT, BASE_LON = 41.6800, 26.5560   # referans merkez (Edirne bölgesi)
ZON_YAYILIM_DERECE = 0.02               # merkezden yaklaşık ~1.5-2 km yayılım

TUM_SENSOR_TIPLERI = ["termal", "kizilotesi", "ses", "rf", "sismik"]

# Bölge "etki seviyesi" profilleri: her profil, (başlangıç olasılığı,
# taban olasılık, yarılanma süresi) aralıklarını tanımlar.
ETKI_PROFILLERI = [
    {"ad": "yüksek", "agirlik": 0.25, "baslangic": (0.30, 0.45), "taban": (0.05, 0.09), "yarilanma_tur": (50, 110)},
    {"ad": "orta",   "agirlik": 0.45, "baslangic": (0.12, 0.22), "taban": (0.025, 0.05), "yarilanma_tur": (100, 180)},
    {"ad": "düşük",  "agirlik": 0.30, "baslangic": (0.04, 0.10), "taban": (0.01, 0.025), "yarilanma_tur": (150, 240)},
]


def _mesafe_metre(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _zon_merkezleri_uret(sayi: int, min_mesafe_m: float) -> list:
    merkezler = []
    deneme = 0
    while len(merkezler) < sayi and deneme < sayi * 300:
        deneme += 1
        lat = BASE_LAT + random.uniform(-ZON_YAYILIM_DERECE, ZON_YAYILIM_DERECE)
        lon = BASE_LON + random.uniform(-ZON_YAYILIM_DERECE, ZON_YAYILIM_DERECE)
        if all(_mesafe_metre(lat, lon, m[0], m[1]) >= min_mesafe_m for m in merkezler):
            merkezler.append((lat, lon))
    return merkezler


def _zonlari_ve_istasyonlari_olustur():
    zon_parametreleri = {}
    istasyonlar = []

    merkezler = _zon_merkezleri_uret(ZON_SAYISI, MIN_ZON_MESAFESI_METRE)
    agirliklar = [p["agirlik"] for p in ETKI_PROFILLERI]

    for i, (lat, lon) in enumerate(merkezler):
        zon_id = f"zon_{i+1}"
        profil = random.choices(ETKI_PROFILLERI, weights=agirliklar, k=1)[0]

        zon_parametreleri[zon_id] = {
            "etki_adi": profil["ad"],
            "baslangic": round(random.uniform(*profil["baslangic"]), 3),
            "taban": round(random.uniform(*profil["taban"]), 3),
            "yarilanma_tur": random.randint(*profil["yarilanma_tur"]),
        }

        # En az 2 sensör tipi - gerçekçi olması için her zonda tam kapsam olmayabilir
        kapsam_sayisi = random.randint(2, len(TUM_SENSOR_TIPLERI))
        zon_sensor_tipleri = random.sample(TUM_SENSOR_TIPLERI, kapsam_sayisi)

        for tip in zon_sensor_tipleri:
            jitter_lat = random.uniform(-0.00025, 0.00025)
            jitter_lon = random.uniform(-0.00025, 0.00025)
            istasyonlar.append({
                "sensor_id": f"{tip}_{zon_id}",
                "sensor_tipi": tip,
                "konum": {"lat": round(lat + jitter_lat, 6), "lon": round(lon + jitter_lon, 6)},
                "zon_id": zon_id,
            })

    return zon_parametreleri, istasyonlar


ZON_PARAMETRELERI, SENSOR_ISTASYONLARI = _zonlari_ve_istasyonlari_olustur()

# Her zonun hangi sensör tiplerine sahip olduğunu hızlıca sorgulamak için
_ZON_SENSOR_TIPLERI = {}
for _ist in SENSOR_ISTASYONLARI:
    _ZON_SENSOR_TIPLERI.setdefault(_ist["zon_id"], set()).add(_ist["sensor_tipi"])


# ============================================================
# 2. VAKA (OLAY) MEKANİZMASI - Kademeli/Gecikmeli Çoklu Sensör Doğrulaması
# ============================================================
# Bir "vaka", bir bölgede başlayan ve zaman içinde diğer sensörlerce
# (hepsi değil, bir kısmı) gecikmeli olarak doğrulanan tek bir olayı
# temsil eder. Bu, projenin temel amacıyla (farklı sensörlerden gelen
# verinin BİRLİKTE değerlendirilerek güvenilirliğin artırılması) birebir
# örtüşen bir davranış üretir.

VAKA_SURE_TUR_ARALIGI = (6, 14)              # vaka toplamda 30-70 saniye sürer
VAKA_ILK_SENSOR_SURE_TUR_ARALIGI = (2, 4)    # ilk fark eden sensörün sinyali kaç tur sürer
VAKA_DOGRULAYAN_SURE_TUR_ARALIGI = (1, 3)    # doğrulayan sensörlerin sinyali kaç tur sürer
VAKA_DOGRULAMA_OLASILIGI = 0.75              # zondaki diğer her sensörün, bu vakayı ZAMANLA doğurulama ihtimali

# Vaka dışı, çok nadir "tek başına" bağımsız blip (sensör gürültüsü /
# yalnız kalan yanlış pozitif benzeri bir durum) - sistemin HER ŞEYİN
# mükemmel senaryolarla açıklanabilir olmadığını da yansıtır.
BAGIMSIZ_GURULTU_OLASILIGI = 0.012

_zon_vaka_durumlari = {}  # zon_id -> aktif vaka dict veya None


def zon_vaka_baslama_olasiligi(zon_id: str, tur: int, artci_aktif: bool) -> float:
    """
    Bir bölgede YENİ bir vakanın bu turda başlama olasılığı. Üstel
    azalma eğrisi kullanılır (başta yüksek, zamanla taban değere
    yaklaşır, asla sıfırlanmaz). Artçı sarsıntı sırasında geçici
    olarak yükselir.
    """
    p = ZON_PARAMETRELERI[zon_id]
    taban = p["taban"] + (p["baslangic"] - p["taban"]) * (0.5 ** (tur / p["yarilanma_tur"]))
    if artci_aktif:
        taban = min(taban + AFTERSHOCK_BONUSU, AFTERSHOCK_MAKS_OLASILIK)
    return taban


def _yeni_vaka_planla(zon_id: str, tur0: int) -> dict:
    """
    Yeni bir vaka için, hangi sensör tipinin İLK fark edeceğini ve
    diğer hangi tiplerin NE ZAMAN (gecikmeli) doğrulayacağını planlar.
    """
    zon_tipleri = sorted(_ZON_SENSOR_TIPLERI[zon_id])
    ilk_tip = random.choice(zon_tipleri)
    toplam_sure = random.randint(*VAKA_SURE_TUR_ARALIGI)

    plan = {ilk_tip: (0, random.randint(*VAKA_ILK_SENSOR_SURE_TUR_ARALIGI))}
    for tip in zon_tipleri:
        if tip == ilk_tip:
            continue
        if random.random() < VAKA_DOGRULAMA_OLASILIGI:
            en_gec_baslangic = max(1, toplam_sure - 2)
            baslama_offset = random.randint(1, en_gec_baslangic)
            sure = random.randint(*VAKA_DOGRULAYAN_SURE_TUR_ARALIGI)
            plan[tip] = (baslama_offset, sure)

    return {"baslangic_tur": tur0, "sure_tur": toplam_sure, "plan": plan, "ilk_tip": ilk_tip}


def _zonlari_guncelle(tur: int, artci_aktif: bool):
    """
    Her tur başında bir kez çağrılır. Her bölge için: aktif bir vaka
    bitmiş mi, devam mı ediyor, yoksa yeni bir tane mi başlıyor - karar verir.
    """
    for zon_id in ZON_PARAMETRELERI:
        aktif_vaka = _zon_vaka_durumlari.get(zon_id)

        if aktif_vaka is not None:
            if tur - aktif_vaka["baslangic_tur"] >= aktif_vaka["sure_tur"]:
                _zon_vaka_durumlari[zon_id] = None
            continue

        olasilik = zon_vaka_baslama_olasiligi(zon_id, tur, artci_aktif)
        if random.random() < olasilik:
            yeni_vaka = _yeni_vaka_planla(zon_id, tur)
            _zon_vaka_durumlari[zon_id] = yeni_vaka
            dogrulayan_tipler = sorted(set(yeni_vaka["plan"]) - {yeni_vaka["ilk_tip"]})
            print(f"  [VAKA BAŞLADI] {zon_id}: ilk fark eden -> {yeni_vaka['ilk_tip']} "
                  f"| doğrulaması planlanan: {dogrulayan_tipler or '(yok - tek sensörlük vaka)'}")


# --- Artçı Sarsıntı ---
AFTERSHOCK_TETIKLENME_OLASILIGI = 1 / 240   # ortalama ~20 dakikada bir (tur=5sn)
AFTERSHOCK_SURE_TUR_ARALIGI = (6, 14)
AFTERSHOCK_BONUSU = 0.25
AFTERSHOCK_MAKS_OLASILIK = 0.65


# ============================================================
# 3. GERÇEKÇİ DEĞER SINIRLARI (tutarlılık - "saçma" değer yok)
# ============================================================
ARKA_PLAN_ARALIGI = {
    "termal": (18, 26), "kizilotesi": (18, 27), "ses": (10, 25),
    "rf": (-105, -85), "sismik": (0.1, 1.5),
}
POZITIF_ARALIGI = {
    "termal": (35, 38), "kizilotesi": (35, 38), "ses": (40, 60),
    "rf": (-70, -50), "sismik": (3.0, 5.0),
}
DRIFT_ADIMI = {
    "termal": 1.0, "kizilotesi": 1.0, "ses": 3, "rf": 4, "sismik": 0.15,
}

TUR_ARALIGI_SANIYE = 5

_istasyon_durumlari = {}  # sensor_id -> {"taban": son arka plan değeri}


def _zaman_damgasi() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def olcum_uret(istasyon: dict, tur: int, artci_aktif: bool) -> dict:
    """
    Bir istasyon için tek bir ölçüm kaydı üretir. Pozitif sinyal kararı
    3 kaynaktan gelebilir (öncelik sırasıyla):
      1. Artçı sarsıntı + sismik sensör -> kesin tetiklenir (fizik gereği)
      2. Bölgenin aktif bir vakası var VE bu sensör o vakanın planında,
         planlanan zaman penceresindeyse -> tetiklenir (gecikmeli doğrulama)
      3. Nadir, vaka dışı bağımsız gürültü
    Aksi halde sensör "arka plan" (normal/gürültüsüz) bir değer üretir.
    """
    tip = istasyon["sensor_tipi"]
    sid = istasyon["sensor_id"]
    zon_id = istasyon["zon_id"]

    durum = _istasyon_durumlari.setdefault(sid, {"taban": sum(ARKA_PLAN_ARALIGI[tip]) / 2})

    pozitif = False

    if tip == "sismik" and artci_aktif:
        pozitif = True
    else:
        vaka = _zon_vaka_durumlari.get(zon_id)
        if vaka is not None and tip in vaka["plan"]:
            baslama_offset, sure = vaka["plan"][tip]
            gecen = tur - vaka["baslangic_tur"]
            if baslama_offset <= gecen < baslama_offset + sure:
                pozitif = True

        if not pozitif and random.random() < BAGIMSIZ_GURULTU_OLASILIGI:
            pozitif = True

    if pozitif:
        lo, hi = POZITIF_ARALIGI[tip]
        ana_deger = round(random.uniform(lo, hi), 1)
    else:
        lo, hi = ARKA_PLAN_ARALIGI[tip]
        adim = DRIFT_ADIMI[tip]
        yeni_taban = durum["taban"] + random.uniform(-adim, adim)
        yeni_taban = max(lo, min(hi, yeni_taban))
        durum["taban"] = yeni_taban
        ana_deger = round(yeni_taban, 1)

    if tip == "termal":
        veri = {"sicaklik_max": ana_deger, "sicaklik_ortalama": round(random.uniform(18, 24), 1)}
    elif tip == "kizilotesi":
        veri = {"sicaklik": ana_deger, "hareket_tespit": pozitif}
    elif tip == "ses":
        veri = {"desibel": round(ana_deger), "insan_sesi_tespit": pozitif}
    elif tip == "rf":
        veri = {"sinyal_gucu": round(ana_deger), "cihaz_tespit": pozitif}
    elif tip == "sismik":
        veri = {"titresim_siddeti": ana_deger, "sure_sn": random.randint(1, 15)}
    else:
        raise ValueError(f"Bilinmeyen sensör tipi: {tip}")

    return {
        "sensor_id": sid,
        "sensor_tipi": tip,
        "konum": istasyon["konum"],
        "zaman_damgasi": _zaman_damgasi(),
        "guven_skoru": round(random.uniform(0.65, 0.95) if pozitif else random.uniform(0.2, 0.6), 2),
        "veri": veri,
    }


# ============================================================
# 4. ANA DÖNGÜ
# ============================================================

def simulasyonu_baslat():
    print(f"Simülatör başlıyor - {ZON_SAYISI} hasar bölgesi, {len(SENSOR_ISTASYONLARI)} istasyon.")
    for zon_id, p in ZON_PARAMETRELERI.items():
        tipler = sorted(_ZON_SENSOR_TIPLERI[zon_id])
        print(f"  {zon_id}: etki={p['etki_adi']:<6} başlangıç=%{p['baslangic']*100:.0f} "
              f"taban=%{p['taban']*100:.1f} yarılanma={p['yarilanma_tur']} tur "
              f"| sensörler: {tipler}")
    print(f"\nHer {TUR_ARALIGI_SANIYE} saniyede bir tur. Durdurmak için Ctrl+C.\n")

    client = mqtt_baglan()
    client.loop_start()

    artci_kalan_tur = 0

    try:
        tur = 0
        while True:
            tur += 1

            if artci_kalan_tur > 0:
                artci_aktif = True
                artci_kalan_tur -= 1
            else:
                artci_aktif = random.random() < AFTERSHOCK_TETIKLENME_OLASILIGI
                if artci_aktif:
                    artci_kalan_tur = random.randint(*AFTERSHOCK_SURE_TUR_ARALIGI) - 1
                    print(f"\n*** ARTÇI SARSINTI BAŞLADI (tur {tur}, ~{(artci_kalan_tur+1)*TUR_ARALIGI_SANIYE}sn sürecek) ***\n")

            # Bölge bazlı vaka durumlarını güncelle (yeni başlat / devam ettir / bitir)
            _zonlari_guncelle(tur, artci_aktif)

            etiket = " [ARTÇI SARSINTI AKTİF]" if artci_aktif else ""
            print(f"--- Tur {tur}{etiket} ---")

            for istasyon in SENSOR_ISTASYONLARI:
                kayit = olcum_uret(istasyon, tur, artci_aktif)
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