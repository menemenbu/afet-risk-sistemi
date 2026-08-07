"""
YZ Motoru - Risk / Öncelik Skorlama
------------------------------------
Bu modül, Gateway'in ürettiği "birleşik bölge" verisini alıp iki
farklı skor üretir:

1. Öncelik Skoru (oncelik_skoru)
   "Burada hayat kurtarma açısından öncelik ne kadar yüksek?"
   Kaynak sinyaller: insan sesi tespiti, vücut sıcaklığına yakın
   termal/kızılötesi okuma, cihaz (telefon) sinyali tespiti.

2. Yapısal Risk Skoru (yapisal_risk_skoru)
   "Bu bölgede yapısal çökme/hasar riski ne kadar yüksek?"
   Kaynak sinyal: sismik titreşim şiddeti.

Bu iki skor kasıtlı olarak AYRI tutulur, çünkü farklı şeyleri ölçerler:
yüksek sismik titreşim "burada biri var" anlamına gelmez, "burası
yapısal olarak tehlikeli" anlamına gelir.

Şu an KURAL TABANLI bir sistemdir (elle belirlenmiş eşikler ve
ağırlıklar). Gerçek/etiketlenmiş afet verisi elde edilirse, ileride
bu ağırlıklar istatistiksel bir modelle (ör. lojistik regresyon)
optimize edilebilir - ama o zamana kadar açıklanabilir olması
(AFAD ekibinin "neden bu bölge öncelikli" sorusuna net cevap
alması) tercih edilir.
"""

# --- Öncelik Skoruna Katkı Veren Sensör Ağırlıkları ---
# Sensör tipinin, "burada hayat belirtisi var" iddiasına ne kadar
# güçlü kanıt oluşturduğunu temsil eder (0-1 arası).
ONCELIK_AGIRLIKLARI = {
    "ses": 0.90,         # insan sesi tespiti çok güçlü bir kanıt
    "termal": 0.85,      # vücut sıcaklığına yakın okuma güçlü kanıt
    "kizilotesi": 0.85,  # aynı şekilde güçlü kanıt
    "rf": 0.55,          # cihaz sinyali orta seviye kanıt (yanlış pozitif olabilir)
}

# Çoklu doğrulama bonusu: aynı bölgeyi kaç farklı sensör TİPİ
# doğruladıysa, öncelik skoruna eklenecek maksimum bonus.
COKLU_DOGRULAMA_MAX_BONUS = 0.20


def _termal_sinyal_puani(veri: dict) -> float:
    """Termal drone: sıcaklık insan vücut sıcaklığına (34-39°C) yakın mı?"""
    sicaklik = veri.get("sicaklik_max", 0)
    return 1.0 if 34 <= sicaklik <= 39 else 0.0


def _kizilotesi_sinyal_puani(veri: dict) -> float:
    """Kızılötesi: sıcaklık aralığı + hareket tespiti birlikte değerlendirilir."""
    sicaklik = veri.get("sicaklik", 0)
    hareket = veri.get("hareket_tespit", False)

    if 34 <= sicaklik <= 39 and hareket:
        return 1.0
    elif 34 <= sicaklik <= 39:
        return 0.6
    return 0.0


def _ses_sinyal_puani(veri: dict) -> float:
    """Ses sensörü: insan sesi doğrudan tespit edildiyse güçlü sinyal."""
    return 1.0 if veri.get("insan_sesi_tespit", False) else 0.0


def _rf_sinyal_puani(veri: dict) -> float:
    """RF/Frekans: cihaz (örn. telefon) tespiti orta seviye sinyal sayılır."""
    return 1.0 if veri.get("cihaz_tespit", False) else 0.0


def _sismik_sinyal_puani(veri: dict) -> float:
    """
    Sismik: titreşim şiddeti arttıkça yapısal risk artar.
    Ölçek gerçek Richter ölçeğiyle birebir değil, sistemimizin
    kendi mock veri aralığına göre kabaca ayarlanmıştır.
    """
    siddet = veri.get("titresim_siddeti", 0)
    if siddet >= 3.0:
        return 1.0
    elif siddet >= 1.0:
        return 0.5
    return 0.1


SINYAL_FONKSIYONLARI = {
    "termal": _termal_sinyal_puani,
    "kizilotesi": _kizilotesi_sinyal_puani,
    "ses": _ses_sinyal_puani,
    "rf": _rf_sinyal_puani,
    "sismik": _sismik_sinyal_puani,
}


def bolge_risk_hesapla(bolge: dict) -> dict:
    """
    Bir bölge (Gateway'in bolgele() çıktısındaki tek bir grup) için
    oncelik_skoru ve yapisal_risk_skoru hesaplar.

    Döner:
        {
            "oncelik_skoru": float (0-1),
            "yapisal_risk_skoru": float (0-1),
            "aciklama": [str, ...]   # her katkının okunabilir dökümü
        }
    """
    kayitlar = bolge["kayitlar"]
    aciklama = []

    # --- Öncelik Skoru Hesabı (sismik hariç tüm sensörler) ---
    toplam_agirlikli_katki = 0.0
    toplam_agirlik = 0.0
    oncelige_katki_veren_tipler = set()

    for kayit in kayitlar:
        tip = kayit["sensor_tipi"]
        if tip == "sismik":
            continue  # sismik ayrı skora gidiyor

        sinyal_fonksiyonu = SINYAL_FONKSIYONLARI[tip]
        sinyal_puani = sinyal_fonksiyonu(kayit["veri"])
        agirlik = ONCELIK_AGIRLIKLARI[tip]
        guven = kayit["guven_skoru"]

        katki = sinyal_puani * guven * agirlik
        toplam_agirlikli_katki += katki
        toplam_agirlik += agirlik

        if sinyal_puani > 0:
            oncelige_katki_veren_tipler.add(tip)
            aciklama.append(
                f"{kayit['sensor_id']} ({tip}): sinyal={sinyal_puani:.1f}, "
                f"güven={guven:.2f} -> katkı={katki:.3f}"
            )

    oncelik_ham = toplam_agirlikli_katki / toplam_agirlik if toplam_agirlik > 0 else 0.0

    # Çoklu doğrulama bonusu: kaç farklı sensör TİPİ pozitif sinyal verdi?
    coklu_dogrulama_orani = len(oncelige_katki_veren_tipler) / len(ONCELIK_AGIRLIKLARI)
    bonus = coklu_dogrulama_orani * COKLU_DOGRULAMA_MAX_BONUS

    oncelik_skoru = min(oncelik_ham + bonus, 1.0)

    if bonus > 0:
        aciklama.append(
            f"Çoklu doğrulama bonusu: {len(oncelige_katki_veren_tipler)} farklı "
            f"sensör tipi sinyal verdi -> +{bonus:.3f}"
        )

    # --- Yapısal Risk Skoru Hesabı (sadece sismik) ---
    sismik_kayitlar = [k for k in kayitlar if k["sensor_tipi"] == "sismik"]
    if sismik_kayitlar:
        yapisal_risk_skoru = max(
            _sismik_sinyal_puani(k["veri"]) * k["guven_skoru"] for k in sismik_kayitlar
        )
    else:
        yapisal_risk_skoru = 0.0

    return {
        "oncelik_skoru": round(oncelik_skoru, 3),
        "yapisal_risk_skoru": round(yapisal_risk_skoru, 3),
        "aciklama": aciklama,
    }