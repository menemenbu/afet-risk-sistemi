"""
Veritabanı Testleri
---------------------
Şema kurulumu, kayıt ekleme/okuma ve oturum bazlı temizleme
davranışının doğru çalıştığını doğrular.
"""

import os

import pytest
from database import Veritabani


@pytest.fixture
def vt(tmp_path):
    """Her test için geçici, izole bir SQLite veritabanı dosyası sağlar."""
    dosya = tmp_path / "test.db"
    veritabani = Veritabani(str(dosya))
    yield veritabani
    veritabani.kapat()


def ornek_kayit():
    return {
        "sensor_id": "termal_01",
        "sensor_tipi": "termal",
        "konum": {"lat": 41.6772, "lon": 26.5556},
        "zaman_damgasi": "2026-08-04T14:23:00Z",
        "guven_skoru": 0.8,
        "veri": {"sicaklik_max": 36.5, "sicaklik_ortalama": 22.0},
    }


def ornek_bolge():
    return {
        "merkez_konum": {"lat": 41.6772, "lon": 26.5556},
        "birlesik_guven_skoru": 0.8,
        "farkli_sensor_tipi_sayisi": 1,
        "kayit_sayisi": 1,
        "sensor_tipleri": ["termal"],
    }


def test_semadaki_tablolar_olusur(vt):
    tablolar = vt.baglanti.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    tablo_adlari = {t[0] for t in tablolar}
    assert {"ham_kayitlar", "bolgeler", "bolge_kayitlar"}.issubset(tablo_adlari)


def test_ham_kayit_eklenir_ve_id_doner(vt):
    kayit_id = vt.ham_kayit_ekle(ornek_kayit())
    assert kayit_id is not None
    sayi = vt.baglanti.execute("SELECT COUNT(*) FROM ham_kayitlar").fetchone()[0]
    assert sayi == 1


def test_bolge_kaydedilir_ve_getirilir(vt):
    kayit_id = vt.ham_kayit_ekle(ornek_kayit())
    vt.bolge_kaydet(ornek_bolge(), [kayit_id], oncelik_skoru=0.9, yapisal_risk_skoru=0.1)

    bolgeler = vt.bolgeleri_getir()
    assert len(bolgeler) == 1
    assert bolgeler[0]["oncelik_skoru"] == 0.9
    assert bolgeler[0]["durum"] == "beklemede"  # varsayılan değer


def test_bolgeleri_temizle_sadece_bolgeleri_siler(vt):
    kayit_id = vt.ham_kayit_ekle(ornek_kayit())
    vt.bolge_kaydet(ornek_bolge(), [kayit_id])

    vt.bolgeleri_temizle()

    bolge_sayisi = vt.baglanti.execute("SELECT COUNT(*) FROM bolgeler").fetchone()[0]
    ham_kayit_sayisi = vt.baglanti.execute("SELECT COUNT(*) FROM ham_kayitlar").fetchone()[0]
    assert bolge_sayisi == 0
    assert ham_kayit_sayisi == 1  # ham_kayitlar etkilenmemeli


def test_tamamen_temizle_her_seyi_siler(vt):
    """Oturum bazlı temizleme: Gateway her başladığında bunu çağırır."""
    kayit_id = vt.ham_kayit_ekle(ornek_kayit())
    vt.bolge_kaydet(ornek_bolge(), [kayit_id])

    vt.tamamen_temizle()

    for tablo in ["ham_kayitlar", "bolgeler", "bolge_kayitlar"]:
        sayi = vt.baglanti.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]
        assert sayi == 0, f"{tablo} temizlenmedi"