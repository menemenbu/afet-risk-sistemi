# Ortak Veri Şeması

Bu doküman, deprem bölgesi afet risk ve öncelik haritası sistemine dahil olan
tüm sensörlerin ürettiği verinin ortak formatını tanımlar. Her sensör
adaptörü, ham veriyi bu şemaya çevirerek Merkezi Gateway'e gönderir.

---

## 1. Genel Zarf (Envelope)

Tüm sensör tiplerinde ortak olan alanlar:

```json
{
  "sensor_id": "string",
  "sensor_tipi": "termal | ses | kizilotesi | rf | sismik",
  "konum": {
    "lat": 0.0,
    "lon": 0.0
  },
  "zaman_damgasi": "ISO 8601",
  "guven_skoru": 0.0,
  "veri": { }
}
```

### Alan Açıklamaları

| Alan | Tip | Açıklama |
|---|---|---|
| `sensor_id` | string | Sensörün benzersiz kimliği (örn. `"termal_drone_01"`) |
| `sensor_tipi` | string | `termal`, `ses`, `kizilotesi`, `rf`, `sismik` değerlerinden biri |
| `konum.lat` / `konum.lon` | float | Sensörün konumu (mock veride sabit değer) |
| `zaman_damgasi` | string | ISO 8601 formatında (örn. `"2026-08-04T14:23:00Z"`) |
| `guven_skoru` | float (0–1) | Elle atanmış sabit değer; senaryoya göre değişebilir |
| `veri` | object | Sensöre özel alanları içerir (aşağıya bakınız) |

---

## 2. Sensöre Özel `veri` Alanları

### Termal Drone
```json
"veri": {
  "sicaklik_max": 36.8,
  "sicaklik_ortalama": 22.0
}
```

### Ses Sensörü
```json
"veri": {
  "desibel": 42,
  "insan_sesi_tespit": true
}
```

### Kızılötesi
```json
"veri": {
  "sicaklik": 35.2,
  "hareket_tespit": true
}
```

### RF / Frekans
```json
"veri": {
  "sinyal_gucu": -65,
  "cihaz_tespit": true
}
```

### Sismik
```json
"veri": {
  "titresim_siddeti": 3.2,
  "sure_sn": 8
}
```

---

## 3. Örnek Tam Kayıtlar

### Termal Drone
```json
{
  "sensor_id": "termal_drone_01",
  "sensor_tipi": "termal",
  "konum": { "lat": 41.6772, "lon": 26.5556 },
  "zaman_damgasi": "2026-08-04T14:23:00Z",
  "guven_skoru": 0.85,
  "veri": {
    "sicaklik_max": 36.8,
    "sicaklik_ortalama": 22.0
  }
}
```

### Ses Sensörü
```json
{
  "sensor_id": "ses_sensoru_01",
  "sensor_tipi": "ses",
  "konum": { "lat": 41.6780, "lon": 26.5561 },
  "zaman_damgasi": "2026-08-04T14:23:05Z",
  "guven_skoru": 0.70,
  "veri": {
    "desibel": 42,
    "insan_sesi_tespit": true
  }
}
```

### Kızılötesi
```json
{
  "sensor_id": "kizilotesi_01",
  "sensor_tipi": "kizilotesi",
  "konum": { "lat": 41.6775, "lon": 26.5558 },
  "zaman_damgasi": "2026-08-04T14:23:10Z",
  "guven_skoru": 0.75,
  "veri": {
    "sicaklik": 35.2,
    "hareket_tespit": true
  }
}
```

### RF / Frekans
```json
{
  "sensor_id": "rf_frekans_01",
  "sensor_tipi": "rf",
  "konum": { "lat": 41.6768, "lon": 26.5550 },
  "zaman_damgasi": "2026-08-04T14:23:15Z",
  "guven_skoru": 0.65,
  "veri": {
    "sinyal_gucu": -65,
    "cihaz_tespit": true
  }
}
```

### Sismik
```json
{
  "sensor_id": "sismik_01",
  "sensor_tipi": "sismik",
  "konum": { "lat": 41.6771, "lon": 26.5553 },
  "zaman_damgasi": "2026-08-04T14:23:20Z",
  "guven_skoru": 0.80,
  "veri": {
    "titresim_siddeti": 3.2,
    "sure_sn": 8
  }
}
```

---

## 4. Kararlar ve Notlar

- **Güven skoru**: Gerçek sensör ölçümü olmadığı için (mock veri kullanıyoruz),
  güven skoru sabit ama örnekten örneğe değişebilen bir değer olarak elle
  atanır. Böylece YZ Motoru ve harita katmanında farklı güven seviyelerinin
  nasıl göründüğü test edilebilir.
- **Konum**: Mock veride sabit koordinatlar kullanılır; gerçek donanıma
  geçilirse hareketli sensörler (örn. drone) için dinamik hale getirilebilir.
- **Zaman damgası**: ISO 8601 standardı kullanılır, böylece zaman senkronu
  Gateway aşamasında kolayca yapılabilir.

---

## 5. Sonraki Adım

Bu şema, **Mock Sensör Veri Üreteçleri** aşamasında her sensör tipi için
örnek veri setleri oluşturmak amacıyla temel alınacaktır.
