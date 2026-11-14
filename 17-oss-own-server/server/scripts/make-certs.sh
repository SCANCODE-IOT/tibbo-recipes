#!/bin/sh
# Свой удостоверяющий центр и сертификат брокера для OSS.
#   ./scripts/make-certs.sh mqtt.example.ru      - по имени сервера
#   ./scripts/make-certs.sh 203.0.113.10         - по IP-адресу
# Ключи RSA-2048: прошивка OSS поддерживает TLS 1.2 с RSA-2048.
# certs/ca.cer (формат DER) нужен для сборки прошивки OSS, см. firmware/.
set -e
HOST="$1"
[ -n "$HOST" ] || { echo "укажите имя или IP сервера: $0 mqtt.example.ru"; exit 1; }
cd "$(dirname "$0")/.."
mkdir -p certs && cd certs
if [ -f ca.key ]; then echo "certs/ca.key уже есть - новый центр не создаю (иначе придётся перешивать все OSS)"; else
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes -keyout ca.key -out ca.crt -subj "/CN=OSS server CA"
fi
case "$HOST" in
  *[!0-9.]*) SAN="DNS:$HOST" ;;
  *) SAN="IP:$HOST" ;;
esac
openssl req -newkey rsa:2048 -sha256 -nodes -keyout server.key -out server.csr -subj "/CN=$HOST"
printf "subjectAltName=%s\nextendedKeyUsage=serverAuth\n" "$SAN" > server.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 1825 -sha256 -extfile server.ext -out server.crt
openssl x509 -in ca.crt -outform der -out ca.cer
rm -f server.csr server.ext
chmod 644 server.key   # брокер в контейнере читает ключ от своего пользователя
echo "готово: certs/server.crt для $HOST, certs/ca.cer - для прошивки OSS. Храните certs/ca.key отдельно и не публикуйте."
