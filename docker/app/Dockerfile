# Afet Risk Sistemi - Python Servisleri (Gateway + Simülatör)
# Aynı imaj hem Gateway'i hem Simülatörü çalıştırmak için kullanılır;
# hangi servisin çalışacağı docker-compose.yml içindeki `command:`
# ayarıyla belirlenir.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Proje modüllerini, gerçek klasör yapısını koruyarak kopyala
# (adaptor.py, gateway.py vb. dosyalardaki göreli import/sys.path
# ayarları bu yapının aynı kalmasına dayanıyor).
COPY adaptor/ adaptor/
COPY db/ db/
COPY ai_engine/ ai_engine/
COPY websocket/ websocket/
COPY gateway/ gateway/
COPY simulator/ simulator/

EXPOSE 8765

CMD ["python", "gateway/gateway.py"]