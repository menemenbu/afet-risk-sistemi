-- Afet Risk Sistemi - Veritabanı Şeması (SQLite)

-- Ham Kayıtlar: Adaptörlerden Gateway'e gelen her bir sensör ölçümü
-- (doğrulamadan geçmiş, MQTT üzerinden alınmış) burada saklanır.
CREATE TABLE IF NOT EXISTS ham_kayitlar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id       TEXT NOT NULL,
    sensor_tipi     TEXT NOT NULL,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    zaman_damgasi   TEXT NOT NULL,
    guven_skoru     REAL NOT NULL,
    veri_json       TEXT NOT NULL,   -- sensöre özel alanlar (JSON string olarak)
    eklenme_zamani  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Bölgeler: Gateway'in konum eşleştirme + zaman senkronu + çakışma
-- çözümü sonucunda ürettiği birleşik bölge özetleri, ve YZ Motoru'nun
-- hesapladığı risk skorları.
CREATE TABLE IF NOT EXISTS bolgeler (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    merkez_lat                  REAL NOT NULL,
    merkez_lon                  REAL NOT NULL,
    birlesik_guven_skoru        REAL NOT NULL,
    farkli_sensor_tipi_sayisi   INTEGER NOT NULL,
    kayit_sayisi                INTEGER NOT NULL,
    sensor_tipleri              TEXT NOT NULL,   -- virgülle ayrılmış liste
    oncelik_skoru                REAL NOT NULL DEFAULT 0,   -- YZ Motoru: hayat kurtarma önceliği
    yapisal_risk_skoru           REAL NOT NULL DEFAULT 0,   -- YZ Motoru: yapısal çökme riski
    guncellenme_zamani          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Bölge - Ham Kayıt İlişki Tablosu: hangi ham kaydın hangi bölgeye
-- dahil edildiğini takip eder (çoktan-çoğa ilişki).
CREATE TABLE IF NOT EXISTS bolge_kayitlar (
    bolge_id  INTEGER NOT NULL REFERENCES bolgeler(id),
    kayit_id  INTEGER NOT NULL REFERENCES ham_kayitlar(id),
    PRIMARY KEY (bolge_id, kayit_id)
);

-- Sık yapılacak sorguları hızlandırmak için indeksler
CREATE INDEX IF NOT EXISTS idx_ham_kayitlar_sensor_tipi ON ham_kayitlar(sensor_tipi);
CREATE INDEX IF NOT EXISTS idx_bolgeler_guven_skoru ON bolgeler(birlesik_guven_skoru);