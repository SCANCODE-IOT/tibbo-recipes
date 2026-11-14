#!/bin/sh
# Добавить устройство OSS на брокер: логин, пароль и права только на свои топики.
#   ./scripts/add-device.sh <устройство> <продукт>
#   ./scripts/add-device.sh wh01 oss1
# Логин OSS - «устройство&продукт», не длиннее 16 знаков (ограничение прошивки).
# Без docker (брокер прямо на сервере): LOCAL=1 ./scripts/add-device.sh wh01 oss1
set -e
DEV="$1"; PK="$2"
[ -n "$DEV" ] && [ -n "$PK" ] || { echo "использование: $0 <устройство> <продукт>"; exit 1; }
case "$DEV$PK" in *[!A-Za-z0-9_-]*) echo "только латинские буквы, цифры, - и _"; exit 1;; esac
USER="$DEV&$PK"
[ ${#USER} -le 16 ] || { echo "логин «$USER» длиннее 16 знаков - сократите имена"; exit 1; }
cd "$(dirname "$0")/.."
CONF=mosquitto/config
PASS=$(openssl rand -hex 16)
if grep -q "^user $USER\$" $CONF/acl; then echo "устройство $USER уже есть: меняю пароль"; else
cat >> $CONF/acl <<ACL

# $DEV (продукт $PK)
user $USER
topic write /sys/$PK/$DEV/thing/event/#
topic read /sys/$PK/$DEV/thing/#
topic readwrite /ext/ntp/$PK/$DEV/#
topic readwrite /shadow/+/$PK/$DEV
ACL
fi
if [ -n "$LOCAL" ]; then
  mosquitto_passwd -b $CONF/passwd "$USER" "$PASS"
  chmod 600 $CONF/passwd $CONF/acl
else
  docker compose exec -T mosquitto mosquitto_passwd -b /mosquitto/config/passwd "$USER" "$PASS"
  docker compose kill -s HUP mosquitto >/dev/null   # брокер перечитывает пароли и права без перезапуска
fi
cat <<OUT

Введите в OSS Companion (Configure -> облако):
  Server URL  : адрес вашего сервера (тот же, что в make-certs.sh)
  Username    : $USER
  Client ID   : $DEV
  Primary Key : $PASS
Пароль показан один раз - сохраните его.
OUT
