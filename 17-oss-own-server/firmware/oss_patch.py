#!/usr/bin/env python3
"""Готовит исходники прошивки OSS для Alibaba Cloud к работе со своим брокером MQTT.

Исходники берутся из репозитория Tibbo: https://github.com/tibbotech/OSS_Apps,
папка OSS_Alicloud/OSS_Ali_APP1. Скрипт меняет только три вещи:
  1. корневой сертификат для MQTT - ваш ca.cer вместо сертификата Alibaba;
  2. порт брокера - 8883 вместо 1883 (TLS остаётся включённым);
  3. версию прошивки, чтобы в приложении было видно, что стоит ваша сборка.

    python3 oss_patch.py <папка OSS_Ali_APP1> <ca.cer> [порт] [версия]
    python3 oss_patch.py OSS_Apps/OSS_Alicloud/OSS_Ali_APP1 certs/ca.cer 8883 OWN1.00.00
"""
import os, re, shutil, sys

def rd(p):
    b = open(p, 'rb').read()
    return b.decode('latin-1'), (b'\r\n' in b)

def wr(p, s, crlf):
    s = s.replace('\r\n', '\n')
    if crlf:
        s = s.replace('\n', '\r\n')
    open(p, 'wb').write(s.encode('latin-1'))

def once(s, old, new, what):
    n = s.count(old)
    if n != 1:
        sys.exit(f'не нашёл ровно одно место «{what}» ({n}). Возможно, Tibbo изменила исходники - сверьте вручную.')
    return s.replace(old, new)

def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    app, ca = sys.argv[1], sys.argv[2]
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 8883
    ver = sys.argv[4] if len(sys.argv) > 4 else 'OWN1.00.00'
    if len(ver) > 20:
        sys.exit('версия не длиннее 20 символов')
    der = open(ca, 'rb').read()
    if der[:1] != b'\x30':
        sys.exit('ca.cer должен быть в формате DER: openssl x509 -in ca.crt -outform der -out ca.cer')

    shutil.copyfile(ca, os.path.join(app, 'Cloud_Cetificates', 'ca.cer'))

    p = os.path.join(app, 'global.tbh'); s, crlf = rd(p)
    s = once(s, '#define MQTT_CER_FILE "AliCloud.cer"', '#define MQTT_CER_FILE "ca.cer"', 'MQTT_CER_FILE')
    s = re.sub(r'(?m)^const OSS_APP_FW_VER="[^"]*"', f'const OSS_APP_FW_VER="{ver}"', s, count=1)
    wr(p, s, crlf)

    p = os.path.join(app, 'alicloud.tbs'); s, crlf = rd(p)
    s = once(s, 'mqtt_start(alicloud_interface,alicloud_url,1883,', f'mqtt_start(alicloud_interface,alicloud_url,{port},', 'порт 1883')
    wr(p, s, crlf)

    tpr = [f for f in os.listdir(app) if f.endswith('.tpr')][0]
    p = os.path.join(app, tpr); s, crlf = rd(p)
    if 'Cloud_Cetificates\\ca.cer' not in s:
        n = max(int(x) for x in re.findall(r'(?m)^\[file(\d+)\]', s)) + 1
        s = s.rstrip('\r\n') + '\n' + '\n'.join([f'[file{n}]', 'path=Cloud_Cetificates\\ca.cer', 'type=binary',
            'format=', 'condition=', 'locked=no', 'location=project']) + '\n'
    wr(p, s, crlf)
    print(f'готово: сертификат ca.cer, порт {port}, версия {ver}. Соберите проект в TIDE.')

if __name__ == '__main__':
    main()
