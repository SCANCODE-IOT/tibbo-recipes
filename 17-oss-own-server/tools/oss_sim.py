#!/usr/bin/env python3
"""Имитатор OSS для проверки своего сервера без устройства.

Шлёт те же сообщения, что прошивка OSS для Alibaba Cloud (tibbotech/OSS_Apps,
OSS_Alicloud): запрос времени, данные в формате Alink, событие устройства.
Логин, Client ID и пароль - те же, что вводятся в OSS Companion.

    pip install paho-mqtt
    python3 oss_sim.py --host mqtt.example.ru --ca ../server/certs/ca.crt \
        --user 'wh01&oss1' --client wh01 --password <пароль> [--hot] [--count 3]

--hot      температура и CO2 выше порогов - проверка оповещений
--count N  сколько раз отправить данные (по умолчанию 3, с паузой --period)
"""
import argparse, json, os, random, ssl, sys, threading, time
import paho.mqtt.client as mqtt

ap = argparse.ArgumentParser()
ap.add_argument('--host', required=True)
ap.add_argument('--port', type=int, default=8883)
ap.add_argument('--ca', help='ca.crt вашего сервера; без него - подключение без TLS (только для проверки внутри сети)')
ap.add_argument('--user', required=True, help='устройство&продукт, как в OSS Companion')
ap.add_argument('--client', required=True)
ap.add_argument('--password', required=True)
ap.add_argument('--count', type=int, default=3)
ap.add_argument('--period', type=float, default=5)
ap.add_argument('--hot', action='store_true')
a = ap.parse_args()
if '&' not in a.user:
    sys.exit('логин должен быть вида устройство&продукт')
dn, pk = a.user.split('&', 1)
got_time = threading.Event()

def on_connect(c, ud, flags, rc, props=None):
    if rc != 0:
        print('брокер отказал:', rc, '- проверьте логин, пароль и Client ID')
        os._exit(1)                                # из потока paho: завершаем сразу
    print('подключился как', a.user)
    for t in (f'/shadow/get/{pk}/{dn}', f'/ext/ntp/{pk}/{dn}/response',
              f'/sys/{pk}/{dn}/thing/event/property/post_reply', f'/sys/{pk}/{dn}/thing/service'):
        c.subscribe(t, 1)
    c.publish(f'/ext/ntp/{pk}/{dn}/request', json.dumps({'deviceSendTime': str(int(time.time() * 1000))}))
    c.publish(f'/shadow/update/{pk}/{dn}', '{"method": "get"}', 1)

def on_message(c, ud, m):
    print('<-', m.topic, m.payload.decode(errors='replace'))
    if m.topic.endswith('/response'):
        got_time.set()

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=a.client)
c.username_pw_set(a.user, a.password)
if a.ca:
    c.tls_set(ca_certs=a.ca, tls_version=ssl.PROTOCOL_TLSv1_2)
c.on_connect, c.on_message = on_connect, on_message
c.connect(a.host, a.port, 60)
c.loop_start()
print('время от сервера:', 'есть' if got_time.wait(10) else 'НЕ ПРИШЛО - проверьте поток Node-RED')
t, h, co2, bat = (33.5, 61.0, 1800, 87) if a.hot else (24.0, 45.0, 650, 87)
for i in range(a.count):
    ts = str(int(time.time())) + '001'            # как в прошивке: секунды и «001»
    params = {'telemetry:temperature': round(t + random.uniform(-.3, .3), 1),
              'telemetry:humidity': round(h + random.uniform(-1, 1), 1),
              'telemetry:co2': int(co2 + random.uniform(-20, 20)),
              'telemetry:BAT_LVL': bat}
    msg = {'id': int(ts), 'params': params, 'version': '1.0', 'method': 'thing.event.property.post'}
    c.publish(f'/sys/{pk}/{dn}/thing/event/property/post', json.dumps(msg, separators=(',', ':')), 0)
    print('->', params)
    if i == 0:
        ev = {'id': int(ts), 'params': {'message': 'Unable to read sensor parameters! (проверка имитатором)'},
              'version': '1.0', 'method': 'thing.event.events:events.post'}
        c.publish(f'/sys/{pk}/{dn}/thing/event/events:events/post', json.dumps(ev, ensure_ascii=False), 0)
    if i < a.count - 1:
        time.sleep(a.period)
time.sleep(1)
c.loop_stop(); c.disconnect()
