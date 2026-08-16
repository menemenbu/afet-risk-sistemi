"""
Gateway (BolgeHavuzu) Testleri
--------------------------------
Konum eşleştirme, zaman senkronu, çakışma çözümü, yinelenen kayıt
tespiti ve durum (görev atama) takibinin doğru çalıştığını doğrular.

Not: Bu testler gerçek bir MQTT broker'ı GEREKTİRMEZ - doğrudan
BolgeHavuzu nesnesiyle çalışırlar (Veritabanı olmadan, sadece
bellek içi mantık test edilir).
"""

from gateway import BolgeHavuzu


def kayit(sensor_id, sensor_tipi, lat, lon, zaman, guven=0.8, veri=None):
    varsayilan_veri = {
        "termal": {"sicaklik_max": 22.0, "sicaklik_ortalama": 22.0},
        "ses": {"desibel": 20, "insan_sesi_tespit": False},
        "sismik": {"titresim_siddeti": 0.5, "sure_sn": 2},
    }
    return {
        "sensor_id": sensor_id,
        "sensor_tipi": sensor_tipi,
        "konum": {"lat": lat, "lon": lon},
        "zaman_damgasi": zaman,
        "guven_skoru": guven,
        "veri": veri if veri is not None else varsayilan_veri.get(sensor_tipi, {}),
    }


def test_yakin_kayitlar_ayni_bolgede_kumelenir():
    havuz = BolgeHavuzu()
    havuz.ekle(kayit("a", "termal", 41.6772, 26.5556, "2026-08-04T14:00:00Z"))
    havuz.ekle(kayit("b", "ses", 41.6773, 26.5557, "2026-08-04T14:00:05Z"))  # ~15m uzakta
    bolgeler = havuz.bolgele()
    assert len(bolgeler) == 1
    assert bolgeler[0]["kayit_sayisi"] == 2


def test_uzak_kayitlar_ayri_bolge_olur():
    havuz = BolgeHavuzu()
    havuz.ekle(kayit("a", "termal", 41.6772, 26.5556, "2026-08-04T14:00:00Z"))
    havuz.ekle(kayit("b", "ses", 41.7000, 26.6000, "2026-08-04T14:00:05Z"))  # çok uzak
    bolgeler = havuz.bolgele()
    assert len(bolgeler) == 2


def test_yinelenen_kayit_reddedilir():
    havuz = BolgeHavuzu()
    k = kayit("a", "termal", 41.6772, 26.5556, "2026-08-04T14:00:00Z")
    ilk_sonuc = havuz.ekle(k)
    ikinci_sonuc = havuz.ekle(dict(k))  # aynı sensor_id + aynı zaman_damgasi
    assert ilk_sonuc is True
    assert ikinci_sonuc is False
    assert len(havuz.kayitlar) == 1


def test_farkli_zaman_damgali_ayni_sensor_kabul_edilir():
    havuz = BolgeHavuzu()
    havuz.ekle(kayit("a", "termal", 41.6772, 26.5556, "2026-08-04T14:00:00Z"))
    sonuc = havuz.ekle(kayit("a", "termal", 41.6772, 26.5556, "2026-08-04T14:00:05Z"))
    assert sonuc is True
    assert len(havuz.kayitlar) == 2


def test_merkez_konum_ortalamadir():
    havuz = BolgeHavuzu()
    havuz.ekle(kayit("a", "termal", 41.6770, 26.5550, "2026-08-04T14:00:00Z"))
    havuz.ekle(kayit("b", "ses", 41.6774, 26.5554, "2026-08-04T14:00:05Z"))
    bolgeler = havuz.bolgele()
    merkez = bolgeler[0]["merkez_konum"]
    assert abs(merkez["lat"] - 41.6772) < 0.0001  # iki noktanın ortalaması


def test_durum_guncelleme_bolge_id_ile_kalicidir():
    """
    REGRESYON TESTİ: Daha önce durum, kayan (ortalama) merkez konuma göre
    anahtarlanıyordu - bölge merkezi yeni veriyle kaydıkça durum
    "kayboluyordu". Artık sabit bir bolge_id kullanılıyor; bu test bunun
    bozulmadığını garanti eder.
    """
    havuz = BolgeHavuzu()
    havuz.ekle(kayit("a", "termal", 41.6772, 26.5556, "2026-08-04T14:00:00Z"))
    bolge_id = havuz.bolgele()[0]["bolge_id"]

    havuz.durum_guncelle(bolge_id, "ekip_gonderildi")

    # Merkezi kaydıracak yeni bir kayıt ekle (aynı bölgeye, ama farklı konumda)
    havuz.ekle(kayit("b", "ses", 41.6777, 26.5562, "2026-08-04T14:00:05Z"))
    bolgeler = havuz.bolgele()

    assert bolgeler[0]["bolge_id"] == bolge_id  # kimlik sabit kalmalı
    assert bolgeler[0]["durum"] == "ekip_gonderildi"  # durum kaybolmamalı
    assert bolgeler[0]["merkez_konum"] != {"lat": 41.6772, "lon": 26.5556}  # merkez gerçekten kaymış olmalı


def test_gecersiz_durum_reddedilir(capsys):
    havuz = BolgeHavuzu()
    havuz.ekle(kayit("a", "termal", 41.6772, 26.5556, "2026-08-04T14:00:00Z"))
    bolge_id = havuz.bolgele()[0]["bolge_id"]
    havuz.durum_guncelle(bolge_id, "gecersiz_bir_durum")
    bolgeler = havuz.bolgele()
    assert bolgeler[0]["durum"] == "beklemede"  # değişmemiş olmalı


def test_kismi_sensor_kapsamiyla_calisir():
    """Bir bölgede sadece 1-2 sensör tipi olsa bile sistem çökmemeli/anlamlı sonuç üretmeli."""
    havuz = BolgeHavuzu()
    havuz.ekle(kayit("a", "sismik", 41.6772, 26.5556, "2026-08-04T14:00:00Z"))
    bolgeler = havuz.bolgele()
    assert len(bolgeler) == 1
    assert bolgeler[0]["farkli_sensor_tipi_sayisi"] == 1