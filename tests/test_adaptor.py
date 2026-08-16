"""
Adaptör Testleri
-----------------
`veri_dogrula()` fonksiyonunun, ortak veri şemasını doğru şekilde
uyguladığını doğrular: geçerli kayıtları kabul etmeli, eksik/bozuk/
yanlış tipte veri içeren kayıtları REDDETMELİ.
"""

import pytest
from adaptor import veri_dogrula


def gecerli_kayit(sensor_tipi="termal", veri=None):
    """Testlerde kullanılacak, tüm zorunlu alanları içeren temel bir kayıt üretir."""
    varsayilan_veri = {
        "termal": {"sicaklik_max": 36.5, "sicaklik_ortalama": 22.0},
        "kizilotesi": {"sicaklik": 35.0, "hareket_tespit": True},
        "ses": {"desibel": 45, "insan_sesi_tespit": True},
        "rf": {"sinyal_gucu": -60, "cihaz_tespit": True},
        "sismik": {"titresim_siddeti": 3.5, "sure_sn": 10},
    }
    return {
        "sensor_id": f"{sensor_tipi}_test_01",
        "sensor_tipi": sensor_tipi,
        "konum": {"lat": 41.6772, "lon": 26.5556},
        "zaman_damgasi": "2026-08-04T14:23:00Z",
        "guven_skoru": 0.8,
        "veri": veri if veri is not None else varsayilan_veri[sensor_tipi],
    }


@pytest.mark.parametrize("tip", ["termal", "kizilotesi", "ses", "rf", "sismik"])
def test_gecerli_kayit_her_sensor_tipinde_gecer(tip):
    gecerli, hata = veri_dogrula(gecerli_kayit(tip))
    assert gecerli, f"Geçerli bir {tip} kaydı reddedildi: {hata}"


def test_eksik_ust_seviye_alan_reddedilir():
    kayit = gecerli_kayit()
    del kayit["guven_skoru"]
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli
    assert "guven_skoru" in hata


def test_gecersiz_sensor_tipi_reddedilir():
    kayit = gecerli_kayit()
    kayit["sensor_tipi"] = "uzaylı_sensörü"
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli


def test_eksik_konum_alani_reddedilir():
    kayit = gecerli_kayit()
    kayit["konum"] = {"lat": 41.67}  # lon eksik
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli


def test_guven_skoru_araligi_disinda_reddedilir():
    kayit = gecerli_kayit()
    kayit["guven_skoru"] = 1.5  # 0-1 aralığı dışında
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli


def test_gecersiz_zaman_damgasi_reddedilir():
    kayit = gecerli_kayit()
    kayit["zaman_damgasi"] = "yarın öğlen"
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli


def test_eksik_veri_alani_reddedilir():
    kayit = gecerli_kayit("termal", veri={"sicaklik_max": 36.0})  # sicaklik_ortalama eksik
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli


def test_none_deger_reddedilir():
    """
    KRİTİK REGRESYON TESTİ: Bir alan var ama değeri None ise, bu daha
    önce sessizce 'geçerli' sayılıyor ve YZ Motorunda çökmeye yol
    açıyordu (TypeError: '<=' not supported ...). Bu test, o hatanın
    bir daha geri gelmediğini garanti eder.
    """
    kayit = gecerli_kayit("termal", veri={"sicaklik_max": None, "sicaklik_ortalama": 22.0})
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli
    assert "None" in hata or "boş" in hata


def test_yanlis_tip_reddedilir():
    kayit = gecerli_kayit("ses", veri={"desibel": "ÇOK YÜKSEK", "insan_sesi_tespit": True})
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli


def test_bool_alaninda_int_reddedilir():
    """bool alanlarına 1/0 gibi int değerler gönderilirse (True/False yerine) reddedilmeli."""
    kayit = gecerli_kayit("rf", veri={"sinyal_gucu": -60, "cihaz_tespit": 1})
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli


def test_sayisal_alanda_bool_reddedilir():
    """Sayısal bir alana bool değer sızmamalı (Python'da bool, int'in alt sınıfıdır)."""
    kayit = gecerli_kayit("sismik", veri={"titresim_siddeti": True, "sure_sn": 10})
    gecerli, hata = veri_dogrula(kayit)
    assert not gecerli