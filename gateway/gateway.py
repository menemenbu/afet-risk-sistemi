"""
Merkezi Gateway Servisi
------------------------
Bu servis, tüm adaptörlerin "sensor/#" topic'lerine yayınladığı
verileri dinler ve şu işlemleri uygular:

1. Mesaj Dinleme    : MQTT broker'a abone olur, gelen her kaydı toplar.
2. Konum Eşleştirme : Birbirine yakın (aynı "bölge" sayılabilecek)
                       kayıtları gruplar.
3. Zaman Senkronu   : Aynı bölgedeki kayıtları belirli bir zaman
                       penceresi içinde eşleştirir.
4. Çakışma Çözümü   : Aynı bölge + zaman penceresinde birden fazla
                       sensörden veri geldiyse, güven skoruna göre
                       ağırlıklı bir "birleşik bölge kaydı" üretir.

Çıktısı, bir sonraki aşamada (YZ Motoru) risk skoru hesaplamak için
kullanılacak "birleşik bölge" listesidir.
"""

import json
import math
import time
import os
import sys
import threading
from datetime import datetime

import paho.mqtt.client as mqtt

# db/ ve ai_engine/ klasörlerindeki modülleri import edebilmek için yol ekle
_mevcut_klasor = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_mevcut_klasor, "..", "db"))
sys.path.insert(0, os.path.join(_mevcut_klasor, "..", "ai_engine"))
sys.path.insert(0, os.path.join(_mevcut_klasor, "..", "websocket"))
from database import Veritabani
from risk_motoru import bolge_risk_hesapla
import ws_server
import control_server

# --- MQTT Ayarları ---
# MQTT_HOST ortam değişkeninden okunur; tanımlı değilse "localhost"
# varsayılır (yerel/Docker dışı çalıştırma için). Docker Compose
# içinde bu değer "mosquitto" (servis adı) olarak ayarlanır.
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = 1883
MQTT_TOPIC = "sensor/#"   # tüm sensör tiplerini dinle

# --- Veritabanı Ayarı ---
DB_DOSYA_YOLU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "afet_risk.db")

# --- Konum Eşleştirme Ayarı ---
# Bu yarıçap içindeki kayıtlar "aynı bölge" sayılır.
KONUM_YARICAPI_METRE = 100

# --- Zaman Senkronu Ayarı ---
# Bu pencere içindeki kayıtlar "aynı zaman dilimi" sayılır.
ZAMAN_PENCERESI_SANIYE = 600  # 10 dakika


def haversine_metre(lat1, lon1, lat2, lon2) -> float:
    """
    İki GPS koordinatı arasındaki mesafeyi metre cinsinden hesaplar
    (Haversine formülü - Dünya'nın küresel yapısını dikkate alır).
    """
    R = 6371000  # Dünya yarıçapı (metre)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def zaman_farki_saniye(zaman1: str, zaman2: str) -> float:
    """İki ISO 8601 zaman damgası arasındaki farkı saniye cinsinden döner."""
    t1 = datetime.fromisoformat(zaman1.replace("Z", "+00:00"))
    t2 = datetime.fromisoformat(zaman2.replace("Z", "+00:00"))
    return abs((t1 - t2).total_seconds())


class BolgeHavuzu:
    """
    Gelen tüm sensör kayıtlarını tutar ve konum + zamana göre
    bölgelere gruplayarak "birleşik bölge" listesi üretir.

    Bir Veritabani nesnesi verilirse, her kayıt kalıcı olarak
    ham_kayitlar tablosuna yazılır ve hesaplanan bölgeler de
    bolgeler tablosuna kaydedilir.
    """

    def __init__(self, veritabani: "Veritabani | None" = None):
        self.kayitlar = []       # şimdiye kadar gelen tüm ham kayıtlar
        self.kayit_id_haritasi = {}  # id(kayit) -> veritabanındaki satır id'si
        self.vt = veritabani

        # Görev atama durumu, bölge konumuna göre (yuvarlanmış lat/lon)
        # anahtarlanır. Bölgeler her mesajda yeniden hesaplandığı için
        # (bolgele() metoduyla) durumun kaybolmaması burada tutulur.
        self.durumlar = {}  # (lat_yuvarlanmis, lon_yuvarlanmis) -> durum string

        # Yinelenen Mesaj Tespiti: (sensor_id, zaman_damgasi) ikilisi
        # daha önce görüldüyse, aynı mesajın MQTT üzerinden (örn. bağlantı
        # kesintisi/yeniden deneme yüzünden) birden fazla kez gelmiş
        # olma ihtimaline karşı kayıt tekrar eklenmez. Bu, güven skorunu
        # ve kayıt sayısını yapay olarak şişirmeyi önler.
        self._gorulen_kayitlar = set()

        # MQTT thread'i (ana thread, loop_forever) ile WebSocket thread'i
        # (panelden gelen durum güncellemeleri) aynı anda self.kayitlar
        # ve self.durumlar'a erişebileceği için, veri bozulmasını
        # önlemek amacıyla bir kilit kullanılır.
        self._kilit = threading.Lock()

    @staticmethod
    def _bolge_id_uret(konum: dict) -> str:
        """
        Bir bölge için KARARLI (sabit) bir kimlik üretir. Bu, o bölgenin
        ham_kayitlar arasından ilk kez o kümeyi açan kaydın konumuna göre
        hesaplanır ve bölge büyüdükçe (yeni kayıtlar eklendikçe) DEĞİŞMEZ.

        ÖNEMLİ: Bu, haritada/panelde GÖSTERİLEN merkez konumdan (ki o,
        tüm kayıtların ortalamasıdır ve her yeni veride hafifçe kayar)
        BİLEREK farklı tutulur. Durum (görev atama) takibi, kayan bir
        değere değil, sabit bu kimliğe göre yapılır - aksi halde
        kullanıcının "ekip gönderildi" dediği bölge, ortalama birkaç
        santim kaydığında durumunu "kaybedebilir".
        """
        return f"{round(konum['lat'], 4)}_{round(konum['lon'], 4)}"

    def ekle(self, kayit: dict) -> bool:
        """
        Yeni bir ham kaydı havuza ekler. Aynı sensörden aynı zaman
        damgasıyla daha önce bir kayıt geldiyse (yinelenen mesaj),
        eklenmez ve False döner.
        """
        yinelenen_anahtar = (kayit["sensor_id"], kayit["zaman_damgasi"])

        with self._kilit:
            if yinelenen_anahtar in self._gorulen_kayitlar:
                return False
            self._gorulen_kayitlar.add(yinelenen_anahtar)

            self.kayitlar.append(kayit)
            if self.vt is not None:
                db_id = self.vt.ham_kayit_ekle(kayit)
                self.kayit_id_haritasi[id(kayit)] = db_id
        return True

    def durum_guncelle(self, bolge_id: str, yeni_durum: str):
        """
        Komuta Paneli'nden gelen bir görev atama güncellemesini işler.
        Durumu belleğe kaydeder, ardından raporu yeniden hesaplayıp
        (veritabanına yazıp + WebSocket'e yayınlayıp) tüm istemcilerin
        güncel durumu görmesini sağlar.
        """
        gecerli_durumlar = {"beklemede", "ekip_gonderildi", "kontrol_edildi"}
        if yeni_durum not in gecerli_durumlar:
            print(f"[HATA] Geçersiz durum: {yeni_durum}")
            return

        with self._kilit:
            self.durumlar[bolge_id] = yeni_durum

        print(f"[DURUM GÜNCELLENDİ] {bolge_id} -> {yeni_durum}")
        self.rapor_yazdir()

    def bolgele(self) -> list[dict]:
        """
        Kayıtları konum + zamana göre gruplar (basit bir kümeleme).
        Her kayıt, ilk uygun gruba eklenir; hiçbir gruba uymuyorsa
        yeni bir grup açılır.

        Döndürdüğü her grup şu bilgileri içerir:
        - merkez_konum: gruptaki ilk kaydın konumu (referans nokta)
        - kayitlar: gruba giren ham kayıtlar
        - sensor_tipleri: gruba katkı veren farklı sensör tipleri
        - birlesik_guven_skoru: güven skorlarının ağırlıklı ortalaması
        """
        gruplar = []

        with self._kilit:
            kayitlar_kopyasi = list(self.kayitlar)

        for kayit in kayitlar_kopyasi:
            uygun_grup = None

            for grup in gruplar:
                mesafe = haversine_metre(
                    kayit["konum"]["lat"], kayit["konum"]["lon"],
                    grup["merkez_konum"]["lat"], grup["merkez_konum"]["lon"]
                )
                zaman_farki = zaman_farki_saniye(
                    kayit["zaman_damgasi"], grup["referans_zaman"]
                )

                if mesafe <= KONUM_YARICAPI_METRE and zaman_farki <= ZAMAN_PENCERESI_SANIYE:
                    uygun_grup = grup
                    break

            if uygun_grup is None:
                # Yeni bölge/grup aç
                gruplar.append({
                    "merkez_konum": kayit["konum"],
                    "referans_zaman": kayit["zaman_damgasi"],
                    "kayitlar": [kayit],
                })
            else:
                uygun_grup["kayitlar"].append(kayit)

        # Her grup için çakışma çözümü uygula (birleşik güven skoru üret)
        birlesik_bolgeler = []
        for grup in gruplar:
            birlesik_bolgeler.append(self._grubu_birlestir(grup))

        return birlesik_bolgeler

    def _grubu_birlestir(self, grup: dict) -> dict:
        """
        Çakışma Çözümü: Bir gruptaki (aynı bölge/zaman) kayıtları,
        güven skoruna göre ağırlıklı birleştirerek tek bir "bölge özeti"
        üretir. Daha yüksek güven skorlu sensörler sonuca daha çok etki eder.
        """
        kayitlar = grup["kayitlar"]
        toplam_guven = sum(k["guven_skoru"] for k in kayitlar)

        # Ağırlıklı birleşik güven skoru (basit ortalama + katkı sayısı bonusu)
        # Not: birden fazla farklı sensör tipi aynı bölgeyi doğruluyorsa
        # bu daha güvenilir bir işaret sayılır, bu yüzden ortalamaya ek
        # olarak "kaç farklı sensör tipi katkı verdi" bilgisini de taşıyoruz.
        ortalama_guven = toplam_guven / len(kayitlar)
        sensor_tipleri = sorted(set(k["sensor_tipi"] for k in kayitlar))

        # Merkez konum: gruba İLK giren kaydın konumu yerine, gruptaki
        # TÜM kayıtların ortalama konumu kullanılır. Bu, tek bir sensörün
        # (özellikle o grubu ilk açan sensörün) hatalı/gürültülü bir GPS
        # okuması göndermesi durumunda tüm bölgenin haritada yanlış
        # konumlanmasını önler - daha fazla sensör katkı verdikçe merkez
        # konum da gerçek değerine yaklaşır.
        ortalama_lat = sum(k["konum"]["lat"] for k in kayitlar) / len(kayitlar)
        ortalama_lon = sum(k["konum"]["lon"] for k in kayitlar) / len(kayitlar)
        merkez_konum = {"lat": round(ortalama_lat, 6), "lon": round(ortalama_lon, 6)}

        # Veri Tazeliği: gruptaki kayıtlar arasında en YENİ zaman damgası,
        # "bu bölgeden en son ne zaman gerçek veri geldi" bilgisini verir.
        # Sensör susmuşsa (öldü/pil bitti/ulaşılamıyor), bu zaman ilerlemez
        # ve arayüz bunu "bayat veri" olarak işaretleyebilir.
        son_guncelleme = max(k["zaman_damgasi"] for k in kayitlar)

        # bolge_id: bu bölgenin SABİT kimliği - grup['merkez_konum']
        # (kümeyi ilk açan kaydın ham konumu) baz alınır, ORTALAMA
        # merkez_konum'dan (yukarıda hesaplanan, kayan) BAĞIMSIZDIR.
        # Durum takibi bu sabit kimlik üzerinden yapılır.
        bolge_id = self._bolge_id_uret(grup["merkez_konum"])
        with self._kilit:
            durum = self.durumlar.get(bolge_id, "beklemede")

        return {
            "bolge_id": bolge_id,
            "merkez_konum": merkez_konum,
            "kayit_sayisi": len(kayitlar),
            "sensor_tipleri": sensor_tipleri,
            "farkli_sensor_tipi_sayisi": len(sensor_tipleri),
            "birlesik_guven_skoru": round(ortalama_guven, 3),
            "durum": durum,
            "son_guncelleme": son_guncelleme,
            "kayitlar": kayitlar,
        }

    def rapor_yazdir(self):
        """
        Şu anki bölge durumunu okunabilir şekilde konsola yazdırır.
        Her bölge için YZ Motoru'ndan öncelik_skoru ve yapisal_risk_skoru
        alınır. Veritabanı bağlıysa, güncel durum bolgeler tablosuna
        da yazılır (önce eskisini temizleyip yenisini yazarak günceller).
        """
        bolgeler = self.bolgele()

        # Her bölge için YZ Motoru skorlarını hesapla
        for bolge in bolgeler:
            risk_sonucu = bolge_risk_hesapla(bolge)
            bolge["oncelik_skoru"] = risk_sonucu["oncelik_skoru"]
            bolge["yapisal_risk_skoru"] = risk_sonucu["yapisal_risk_skoru"]
            bolge["aciklama"] = risk_sonucu["aciklama"]

        if self.vt is not None:
            with self._kilit:
                self.vt.bolgeleri_temizle()
                for bolge in bolgeler:
                    kayit_idleri = [
                        self.kayit_id_haritasi[id(k)] for k in bolge["kayitlar"]
                        if id(k) in self.kayit_id_haritasi
                    ]
                    self.vt.bolge_kaydet(
                        bolge, kayit_idleri,
                        oncelik_skoru=bolge["oncelik_skoru"],
                        yapisal_risk_skoru=bolge["yapisal_risk_skoru"],
                        durum=bolge["durum"],
                    )

        print(f"\n{'=' * 60}")
        print(f"BÖLGE RAPORU  ({len(self.kayitlar)} ham kayıt -> {len(bolgeler)} bölge)")
        print(f"{'=' * 60}")

        for i, bolge in enumerate(sorted(
                bolgeler, key=lambda b: b["oncelik_skoru"], reverse=True), start=1):
            konum = bolge["merkez_konum"]
            print(f"\nBölge {i}: ({konum['lat']}, {konum['lon']})")
            print(f"  Katkı veren sensör tipleri : {', '.join(bolge['sensor_tipleri'])}")
            print(f"  Farklı sensör tipi sayısı  : {bolge['farkli_sensor_tipi_sayisi']}")
            print(f"  Toplam kayıt sayısı        : {bolge['kayit_sayisi']}")
            print(f"  Birleşik güven skoru       : {bolge['birlesik_guven_skoru']}")
            print(f"  >>> ÖNCELİK SKORU          : {bolge['oncelik_skoru']}")
            print(f"  >>> YAPISAL RİSK SKORU     : {bolge['yapisal_risk_skoru']}")
            print(f"  Durum                      : {bolge['durum']}")
            if bolge["aciklama"]:
                print(f"  Açıklama:")
                for satir in bolge["aciklama"]:
                    print(f"    - {satir}")

        # Güncel bölge durumunu WebSocket üzerinden bağlı istemcilere yayınla
        # (harita/panel bu mesajı dinleyip anlık güncellenecek)
        ws_server.yayinla({
            "tip": "bolge_guncelleme",
            "toplam_ham_kayit": len(self.kayitlar),
            "bolgeler": [
                {
                    "bolge_id": bolge["bolge_id"],
                    "konum": bolge["merkez_konum"],
                    "sensor_tipleri": bolge["sensor_tipleri"],
                    "kayit_sayisi": bolge["kayit_sayisi"],
                    "birlesik_guven_skoru": bolge["birlesik_guven_skoru"],
                    "oncelik_skoru": bolge["oncelik_skoru"],
                    "yapisal_risk_skoru": bolge["yapisal_risk_skoru"],
                    "durum": bolge["durum"],
                    "son_guncelleme": bolge["son_guncelleme"],
                }
                for bolge in bolgeler
            ],
        })


# --- MQTT Callback Fonksiyonları ---

havuz = None  # gateway_baslat() içinde Veritabani ile birlikte oluşturulacak


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Broker'a bağlanıldı (kod: {reason_code}). '{MQTT_TOPIC}' dinleniyor...")
    client.subscribe(MQTT_TOPIC)


def on_message(client, userdata, msg):
    try:
        kayit = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        print(f"[HATA] Geçersiz JSON mesaj alındı: {msg.topic}")
        return

    yeni_mi = havuz.ekle(kayit)
    if not yeni_mi:
        print(f"[YİNELENEN - ATLANDI] {kayit['sensor_id']} "
              f"({kayit['zaman_damgasi']}) daha önce işlendi.")
        return

    print(f"[ALINDI <- {msg.topic}] {kayit['sensor_id']} "
          f"(güven: {kayit['guven_skoru']})")

    # SAVUNMA KATMANI: Adaptördeki doğrulamayı bir şekilde atlatan
    # (örn. ileride eklenecek yeni bir sensör tipinde öngörülmemiş bir
    # değer kombinasyonu) beklenmedik bir veri, burada YZ Motoru veya
    # veritabanı katmanında bir hataya yol açabilir. TEK bir bozuk
    # kaydın, TÜM sistemin mesaj işlemeyi durdurmasına neden olmaması
    # için bu adım try/except ile korunur - proje felsefesi "eksik/
    # bozuk veri olsa bile elimizdekiyle çalışmaya devam et" olduğu
    # için bu katman kritik önemde.
    try:
        havuz.rapor_yazdir()
    except Exception as e:
        print(f"[KRİTİK HATA - YAKALANDI] rapor_yazdir sırasında hata: "
              f"{type(e).__name__}: {e}")
        print("Gateway çalışmaya devam ediyor, bu kayıt/tur atlandı.")


def ws_mesaj_geldi(mesaj: dict):
    """
    WebSocket istemcisinden (Komuta Paneli) gelen mesajları işler.
    Şu an tek mesaj tipi destekleniyor: "durum_guncelleme".
    """
    if mesaj.get("tip") == "durum_guncelleme":
        havuz.durum_guncelle(mesaj["bolge_id"], mesaj["durum"])
    else:
        print(f"[WebSocket] Bilinmeyen mesaj tipi: {mesaj.get('tip')}")


def gateway_baslat():
    global havuz

    vt = Veritabani(DB_DOSYA_YOLU)
    # Her Gateway başlangıcı "temiz bir oturum" sayılır - önceki
    # çalıştırmadan (örn. Docker kapatılıp tekrar açılmadan önceki)
    # kayıtlar bu oturuma taşınmaz. Docker'da `docker compose down` ile
    # kapatılıp `up` ile tekrar açıldığında, bir önceki oturumun tüm
    # verileri burada silinmiş olur.
    vt.tamamen_temizle()
    havuz = BolgeHavuzu(veritabani=vt)
    print(f"Veritabanı hazır (yeni oturum - önceki kayıtlar temizlendi): {DB_DOSYA_YOLU}")

    ws_server.baslat()
    ws_server.mesaj_dinleyicisi_ayarla(ws_mesaj_geldi)
    control_server.baslat()
    time.sleep(0.5)  # WebSocket/Kontrol sunucularının thread'de başlaması için kısa bekleme

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT)
    print("Gateway servisi çalışıyor. Durdurmak için Ctrl+C.")
    client.loop_forever()


if __name__ == "__main__":
    try:
        gateway_baslat()
    except KeyboardInterrupt:
        print("\nGateway servisi durduruldu.")