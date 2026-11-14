#!/usr/bin/env python3
"""Сборка файла .tcu для обновления OSS через приложение OSS Companion.

Повторяет формат скрипта Tibbo tcu-pack.ps1 из репозитория tibbotech/OSS_Apps:
TiOS + APP0 + APP1 (каждое приложение дополняется до блока 4096 байт)
и манифест с типом устройства и версией TiOS.

    python3 tcu_pack.py tios-wm2000-4_03_07.bin APP0.tpc APP1.tpc OSS_FW.tcu
"""
import os, re, struct, sys

BLOCK = 4096

def pad(b):
    r = len(b) % BLOCK
    return b if r == 0 else b + bytes(BLOCK - r)

def item(kind, data):
    checksum = (-sum(data)) & 0xFFFFFFFF          # дополнение суммы байтов до нуля
    return struct.pack('<iiI', kind, len(data), checksum) + data

def pack(tios, app0, app1):
    tios_b, a0, a1 = (open(p, 'rb').read() for p in (tios, app0, app1))
    m = re.match(r'tios-\w+?-(.+)\.bin$', os.path.basename(tios))
    if not m:
        sys.exit('имя файла TiOS должно быть вида tios-wm2000-4_03_07.bin')
    tios_ver = m.group(1).replace('_', '.')
    fields = ['WM2000', '', '', tios_ver, '', '', '', '', '', '01.00.00']
    manifest = b''.join(struct.pack('<H', len(f)) + f.encode('ascii') for f in fields)
    items = [item(9, manifest), item(6, tios_b + pad(a0) + pad(a1))]
    return struct.pack('<ii', len(items), sum(len(i) for i in items)) + b''.join(items)

if __name__ == '__main__':
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    out = pack(*sys.argv[1:4])
    open(sys.argv[4], 'wb').write(out)
    print(sys.argv[4], len(out), 'байт')
