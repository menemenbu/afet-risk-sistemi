"""
Veritabanı Modülü
------------------
SQLite üzerinde ham sensör kayıtlarını ve Gateway'in ürettiği
birleşik bölgeleri kalıcı olarak saklar.

Kullanım (Gateway içinden):
    from db.database import Veritabani

    vt = Veritabani("afet_risk.db")
    kayit_id = vt.ham_kayit_ekle(kayit)
    vt.bolge_kaydet(bolge, kayit_id_listesi)
"""

import json
import os
import sqlite3


class Veritabani:
    def __init__(self, db_dosya_yolu: str = "afet_risk.db"):
        self.db_dosya_yolu = db_dosya_yolu
        self.baglanti = sqlite3.connect(db_dosya_yolu)
        self.baglanti.row_factory = sqlite3.Row
        self._semayi_kur()

    def _semayi_kur(self):
        """schema.sql dosyasını okuyup tabloları oluşturur (yoksa)."""
        mevcut_klasor = os.path.dirname(os.path.abspath(__file__))
        schema_yolu = os.path.join(mevcut_klasor, "schema.sql")
        with open(schema_yolu, "r", encoding="utf-8") as f:
            self.baglanti.executescript(f.read())
        self.baglanti.commit()

    def ham_kayit_ekle(self, kayit: dict) -> int:
        """
        Doğrulanmış bir sensör kaydını ham_kayitlar tablosuna ekler.
        Eklenen satırın id'sini döner (bolge_kayitlar ilişkisi için gerekir).
        """
        imlec = self.baglanti.execute(
            """
            INSERT INTO ham_kayitlar
                (sensor_id, sensor_tipi, lat, lon, zaman_damgasi, guven_skoru, veri_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kayit["sensor_id"],
                kayit["sensor_tipi"],
                kayit["konum"]["lat"],
                kayit["konum"]["lon"],
                kayit["zaman_damgasi"],
                kayit["guven_skoru"],
                json.dumps(kayit["veri"], ensure_ascii=False),
            ),
        )
        self.baglanti.commit()
        return imlec.lastrowid

    def bolge_kaydet(self, bolge: dict, kayit_id_listesi: list[int],
                      oncelik_skoru: float = 0.0, yapisal_risk_skoru: float = 0.0) -> int:
        """
        Gateway'in ürettiği birleşik bir bölgeyi bolgeler tablosuna ekler
        ve o bölgeye giren ham kayıtları bolge_kayitlar ile ilişkilendirir.
        oncelik_skoru ve yapisal_risk_skoru, YZ Motoru tarafından
        hesaplanıp buraya parametre olarak verilir.
        """
        imlec = self.baglanti.execute(
            """
            INSERT INTO bolgeler
                (merkez_lat, merkez_lon, birlesik_guven_skoru,
                 farkli_sensor_tipi_sayisi, kayit_sayisi, sensor_tipleri,
                 oncelik_skoru, yapisal_risk_skoru)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bolge["merkez_konum"]["lat"],
                bolge["merkez_konum"]["lon"],
                bolge["birlesik_guven_skoru"],
                bolge["farkli_sensor_tipi_sayisi"],
                bolge["kayit_sayisi"],
                ",".join(bolge["sensor_tipleri"]),
                oncelik_skoru,
                yapisal_risk_skoru,
            ),
        )
        bolge_id = imlec.lastrowid

        for kayit_id in kayit_id_listesi:
            self.baglanti.execute(
                "INSERT OR IGNORE INTO bolge_kayitlar (bolge_id, kayit_id) VALUES (?, ?)",
                (bolge_id, kayit_id),
            )

        self.baglanti.commit()
        return bolge_id

    def bolgeleri_getir(self, min_oncelik_skoru: float = 0.0) -> list[dict]:
        """
        Kayıtlı bölgeleri, öncelik skoruna göre azalan sırada döner.
        min_oncelik_skoru ile düşük öncelikli bölgeleri filtreleyebilirsin.
        """
        satirlar = self.baglanti.execute(
            """
            SELECT * FROM bolgeler
            WHERE oncelik_skoru >= ?
            ORDER BY oncelik_skoru DESC
            """,
            (min_oncelik_skoru,),
        ).fetchall()
        return [dict(satir) for satir in satirlar]

    def bolgeleri_temizle(self):
        """
        bolgeler ve bolge_kayitlar tablolarını boşaltır.
        Gateway her yeni mesajda tüm bölgeleri yeniden hesapladığı için,
        veritabanının her zaman GÜNCEL bölge durumunu yansıtması adına
        eski bölge kayıtları önce silinir, sonra yenileri yazılır.
        (ham_kayitlar tablosu buradan etkilenmez, o kalıcı geçmiş kayıttır.)
        """
        self.baglanti.execute("DELETE FROM bolge_kayitlar")
        self.baglanti.execute("DELETE FROM bolgeler")
        self.baglanti.commit()

    def kapat(self):
        self.baglanti.close()


if __name__ == "__main__":
    # Basit bir doğrulama: veritabanını kur ve tabloların oluştuğunu göster
    vt = Veritabani("test.db")
    print("Veritabanı oluşturuldu, tablolar hazır: test.db")
    vt.kapat()
    os.remove("test.db")
    print("Test dosyası temizlendi. Şema doğrulandı.")