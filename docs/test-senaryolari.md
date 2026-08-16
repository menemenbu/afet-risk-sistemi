# Test Senaryoları — Manuel Kontrol Listesi

Bu doküman, otomatik testlerin (`tests/` klasörü, `pytest` ile
çalıştırılır) **kapsayamadığı** kısımları kapsar: tarayıcı tabanlı
davranışlar, Docker akışı, ve sistemin uçtan uca gerçek zamanlı
çalışması. Aynı zamanda jüri sunumunda **prova senaryosu** olarak
kullanılabilir.

Her senaryonun yanına ✅ / ❌ işareti koyarak ilerleyebilirsin.

---

## 1. Ortam Kurulumu

| # | Adım | Beklenen Sonuç |
|---|---|---|
| 1.1 | `docker compose up -d --build` çalıştır | Hata vermeden 3 container ayağa kalkar: `afet-mqtt-broker`, `afet-gateway`, `afet-frontend` |
| 1.2 | `docker ps` ile kontrol et | Üç container da `Up` durumda görünür |
| 1.3 | `docker compose logs gateway` | `"Broker'a bağlanıldı"`, `"WebSocket sunucusu çalışıyor"`, `"Kontrol Sunucusu çalışıyor"` satırlarını içerir |
| 1.4 | Tarayıcıda `http://localhost:8000` aç | Canlı Harita sayfası boş bir haritayla açılır, hata vermez |

---

## 2. Oturum (Session) Davranışı

| # | Adım | Beklenen Sonuç |
|---|---|---|
| 2.1 | Simülatörü panelden başlat, ~1 dakika bekle | Harita/panelde en az bir bölge oluşur |
| 2.2 | Yeni bir tarayıcı sekmesinde aynı sayfayı aç (yeni veri gelmeden) | Mevcut bölgeler **anında** görünür (boş başlamaz) |
| 2.3 | `docker compose down` sonra `docker compose up -d` | Yeniden açılan Gateway logunda `"yeni oturum - önceki kayıtlar temizlendi"` yazar |
| 2.4 | Haritayı tekrar aç | Önceki oturumdan **hiçbir bölge kalmamış** olmalı (temiz başlangıç) |

---

## 3. Canlı Harita

| # | Adım | Beklenen Sonuç |
|---|---|---|
| 3.1 | Simülatörü başlat, birkaç dakika izle | Bölgeler haritada renkli dairelerle belirir (yeşil=düşük, sarı=orta, kırmızı=yüksek öncelik) |
| 3.2 | Öncelik skoru ≥%70 olan bir bölge oluştuğunda gözle | Daire etrafında "nabız" (genişleyen halka) animasyonu görünür |
| 3.3 | Bir bölgenin dairesine tıkla | Popup açılır: öncelik %, yapısal risk %, güven %, sensör tipleri, durum, "X önce" tazelik bilgisi |
| 3.4 | Sağ paneldeki bölge listesinden bir karta tıkla | Harita o bölgeye "uçarak" yakınlaşır (flyTo) |
| 3.5 | Bir bölgeyi 5+ dakika güncellenmeden bırak (simülatörü durdurup bekle) | Popup'taki tazelik metni "⚠ BAYAT VERİ" uyarısına döner (sarı) |
| 3.6 | 15+ dakika sonra tekrar kontrol et | "⚠ SENSÖR SESSİZ" uyarısına döner (kırmızı), dairenin kenarı kesik çizgili olur |

---

## 4. Komuta Paneli

| # | Adım | Beklenen Sonuç |
|---|---|---|
| 4.1 | `http://localhost:8000/panel.html` aç | Özet kartları (toplam bölge, yüksek öncelik, beklemede, kontrol edildi) görünür |
| 4.2 | "▶ Simülatörü Başlat" butonuna tıkla | Buton "✓ Simülatör Başlatıldı" yazısına döner; birkaç saniye içinde tablo dolmaya başlar |
| 4.3 | Butona tekrar tıkla (simülatör zaten çalışırken) | "✓ Simülatör Zaten Çalışıyor" yazısı görünür (ikinci bir süreç başlamaz) |
| 4.4 | Bir bölge satırında "Ekip Gönderildi" butonuna tıkla | Durum rozeti güncellenir, "Beklemede" sayacı azalır |
| 4.5 | Aynı anda harita sekmesi açıksa oraya geç | Aynı bölgenin popup'ında da durum "Ekip Gönderildi" olarak görünür (senkron) |
| 4.6 | Filtre butonlarını dene (Beklemede / Ekip Gönderildi / Kontrol Edildi / Sadece Yüksek Öncelik) | Tablo doğru şekilde filtrelenir |
| 4.7 | Simülatörü uzun süre çalıştırıp bir bölgenin durumunu değiştir, sonra o bölgeye yeni veri gelmesini bekle | Durum değişmemiş kalır (yeni veri durumu sıfırlamaz) |

---

## 5. Sayfa Geçişleri

| # | Adım | Beklenen Sonuç |
|---|---|---|
| 5.1 | Haritada sağ üstteki "Komuta Paneli →" butonuna tıkla | Panel sayfasına geçer |
| 5.2 | Panelde sol üstteki "← Canlı Harita" butonuna tıkla | Harita sayfasına geri döner |

---

## 6. Bağlantı Dayanıklılığı

| # | Adım | Beklenen Sonuç |
|---|---|---|
| 6.1 | Harita açıkken sağ üstteki bağlantı noktasını gözle | Yeşil ve "BAĞLI" yazıyor olmalı |
| 6.2 | `docker compose stop gateway` çalıştır | Bağlantı noktası kırmızıya döner, "BAĞLANTI YOK" yazar |
| 6.3 | `docker compose start gateway` ile tekrar başlat | Birkaç saniye içinde otomatik olarak yeniden bağlanır, nokta tekrar yeşile döner |

---

## 7. Dayanıklılık — Bozuk/Eksik Veri Senaryosu

Projenin temel amacı "eksik veri olsa bile sistemin çalışmaya devam
etmesi" olduğu için bu senaryo özellikle önemlidir.

| # | Adım | Beklenen Sonuç |
|---|---|---|
| 7.1 | `docker exec -it afet-mqtt-broker mosquitto_pub -t "sensor/termal" -m '{"sensor_id":"test","sensor_tipi":"termal","konum":{"lat":41.67,"lon":26.55},"zaman_damgasi":"2026-01-01T00:00:00Z","guven_skoru":0.8,"veri":{"sicaklik_max":null,"sicaklik_ortalama":22.0}}'` çalıştır (bilerek bozuk `null` değer) | Gateway logunda `"[KRİTİK HATA - YAKALANDI]"` görünür AMA süreç durmaz |
| 7.2 | Aynı anda harita/panel açık tut, sonra simülatörü tekrar başlat | Sistem normal şekilde veri almaya devam eder - bozuk mesaj sistemi kilitlemez |
| 7.3 | Aynı bozuk mesajı `mosquitto_pub` ile 2 kez art arda gönder | İkincisi `"[YİNELENEN - ATLANDI]"` olarak loglanır (tekrar sayılmaz) |

---

## 8. Simülatör Gerçekçilik Kontrolü

| # | Adım | Beklenen Sonuç |
|---|---|---|
| 8.1 | Simülatörü başlat, konsol/log çıktısını izle | Zaman zaman `"[VAKA BAŞLADI] zon_X: ilk fark eden -> Y"` satırları görünür |
| 8.2 | Bir vaka başladığında birkaç tur bekle | Aynı bölgede, birkaç tur SONRA diğer sensör tiplerinin de pozitif okuma yaptığını (log/harita üzerinden) gözlemle - hepsi AYNI ANDA tetiklenmemeli |
| 8.3 | Simülatörü 20-30 dakika açık bırak | Konsolda bazen `"*** ARTÇI SARSINTI BAŞLADI ***"` mesajı görülebilir (garanti değil, olasılıksal) |
| 8.4 | Artçı sarsıntı sırasında sismik sensörlü bölgeleri gözle | O bölgelerin yapısal risk skoru belirgin şekilde yükselir |

---

## 9. Otomatik Testler (Referans)

Bu manuel senaryolara ek olarak, arka uç mantığı `pytest` ile otomatik
test edilir:

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

36 test; veri doğrulama, risk skorlama, bölge kümeleme, durum takibi
ve veritabanı işlemlerini kapsar. Kod üzerinde değişiklik yapıldığında
bu testlerin tekrar çalıştırılması, bir önceki davranışın bozulup
bozulmadığını (regresyon) otomatik olarak gösterir.