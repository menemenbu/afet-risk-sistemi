"""
YZ Motoru (Risk Skorlama) Testleri
------------------------------------
`bolge_risk_hesapla()` fonksiyonunun, sensör verisinden doğru öncelik
ve yapısal risk skorları ürettiğini doğrular.
"""

from risk_motoru import bolge_risk_hesapla


def kayit(sensor_tipi, veri, guven_skoru=0.8, sensor_id=None):
    return {
        "sensor_id": sensor_id or f"{sensor_tipi}_01",
        "sensor_tipi": sensor_tipi,
        "konum": {"lat": 41.6772, "lon": 26.5556},
        "zaman_damgasi": "2026-08-04T14:23:00Z",
        "guven_skoru": guven_skoru,
        "veri": veri,
    }


def bolge(kayitlar):
    return {"merkez_konum": {"lat": 41.6772, "lon": 26.5556}, "kayitlar": kayitlar}


def test_bos_bolge_sifir_skor_verir():
    sonuc = bolge_risk_hesapla(bolge([]))
    assert sonuc["oncelik_skoru"] == 0.0
    assert sonuc["yapisal_risk_skoru"] == 0.0


def test_insan_vucut_sicakligi_yuksek_sinyal_verir():
    k = kayit("termal", {"sicaklik_max": 36.5, "sicaklik_ortalama": 22.0})
    sonuc = bolge_risk_hesapla(bolge([k]))
    assert sonuc["oncelik_skoru"] > 0.5


def test_ortam_sicakligi_dusuk_sinyal_verir():
    k = kayit("termal", {"sicaklik_max": 20.0, "sicaklik_ortalama": 19.0})
    sonuc = bolge_risk_hesapla(bolge([k]))
    assert sonuc["oncelik_skoru"] == 0.0


def test_insan_sesi_tespiti_sinyal_verir():
    k = kayit("ses", {"desibel": 50, "insan_sesi_tespit": True})
    sonuc = bolge_risk_hesapla(bolge([k]))
    assert sonuc["oncelik_skoru"] > 0.5


def test_coklu_sensor_dogrulamasi_skoru_artirir():
    """Aynı bölgeyi birden fazla farklı sensör tipi doğruladığında,
    öncelik skoru TEK sensöre göre daha yüksek olmalı (çoklu doğrulama bonusu)."""
    tek_sensor = bolge([kayit("termal", {"sicaklik_max": 36.5, "sicaklik_ortalama": 22.0})])
    coklu_sensor = bolge([
        kayit("termal", {"sicaklik_max": 36.5, "sicaklik_ortalama": 22.0}),
        kayit("ses", {"desibel": 50, "insan_sesi_tespit": True}),
        kayit("rf", {"sinyal_gucu": -60, "cihaz_tespit": True}),
    ])
    tek_skor = bolge_risk_hesapla(tek_sensor)["oncelik_skoru"]
    coklu_skor = bolge_risk_hesapla(coklu_sensor)["oncelik_skoru"]
    assert coklu_skor > tek_skor


def test_sismik_ayri_bir_skor_uretir():
    """Sismik veri, öncelik skorunu DEĞİL, yapısal risk skorunu etkilemeli
    (yüksek titreşim 'burada insan var' anlamına gelmez, 'burası tehlikeli' demektir)."""
    k = kayit("sismik", {"titresim_siddeti": 4.5, "sure_sn": 12})
    sonuc = bolge_risk_hesapla(bolge([k]))
    assert sonuc["yapisal_risk_skoru"] > 0.5
    assert sonuc["oncelik_skoru"] == 0.0  # sismik tek başına öncelik skoruna katkı vermemeli


def test_dusuk_guven_skoru_katkiyi_azaltir():
    yuksek_guven = bolge([kayit("ses", {"desibel": 50, "insan_sesi_tespit": True}, guven_skoru=0.9)])
    dusuk_guven = bolge([kayit("ses", {"desibel": 50, "insan_sesi_tespit": True}, guven_skoru=0.3)])
    yuksek_skor = bolge_risk_hesapla(yuksek_guven)["oncelik_skoru"]
    dusuk_skor = bolge_risk_hesapla(dusuk_guven)["oncelik_skoru"]
    assert yuksek_skor > dusuk_skor


def test_aciklama_listesi_doludur():
    k = kayit("ses", {"desibel": 50, "insan_sesi_tespit": True})
    sonuc = bolge_risk_hesapla(bolge([k]))
    assert len(sonuc["aciklama"]) > 0