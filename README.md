# Рецепты Tibbo: готовые решения автоматизации

Двадцать задач, решённых от начала до конца на оборудовании [Tibbo Technology](https://tibbo.com): проект TIDE на Tibbo BASIC или проект [AppBlocks](https://appblocks.io), спецификация (`bom.csv`), раскладка Tibbit по сокетам с бюджетом питания и инструкция по сборке и настройке.

Описания и страницы со спецификацией и ценами - на [tibbo.ru/recipes](https://tibbo.ru/recipes).

| № | Рецепт | Плата | AppBlocks |
|---|---|---|---|
| 01 | [Шлюз Modbus RTU → MQTT](01-modbus-rtu-mqtt/) - Опрос приборов RS-485 по Modbus RTU и публикация значений в MQTT, запись уставок обратно. | TPP2(G2) | да |
| 02 | [Управление освещением: реле, веб-страница, расписание](02-lighting/) - Четыре канала освещения через контакторы: расписание, веб-страница, кнопки на стене, время по SNTP. | TPP2(G2) | да |
| 03 | [Учёт электроэнергии и воды](03-metering/) - Счётчики электроэнергии по Modbus RTU и до 4 счётчиков воды с импульсным выходом: показания на веб-странице и в MQTT. | TPP2(G2) | да |
| 04 | [Мониторинг серверной: температура, влажность, протечка](04-server-room/) - Датчик температуры и влажности RS-485, протечка, дверь и два резервных входа, сирена и зуммер, пороги на веб-странице, MQTT. | TPP2(G2) | да |
| 05 | [СКУД на одну дверь](05-access-control/) - Считыватель Wiegand, замок, кнопка выхода, датчик двери и пожарный вход; список карт и журнал на веб-странице с паролем. | TPP2(G2) | да |
| 06 | [«Умный» Serial-over-IP для весов (DS1100)](06-scale-ds1100/) - Весы с RS-232 в сети: прозрачный TCP-порт для старых программ, вес на веб-странице, HTTP для учётной системы и Modbus TCP. | DS1100 | - |
| 07 | [Телеметрия удалённого объекта по LTE](07-lte-telemetry/) - Четыре «сухих контакта» и температура в шкафу уходят в MQTT через LTE: сразу при изменении и отчётом раз в 15 минут. | TPP2(G2) | да |
| 08 | [Термостат и вентиляция (0-10 В)](08-thermostat-0-10v/) - Датчик температуры и влажности RS-485, нагреватель на реле, клапан и EC-вентилятор 0-10 В, уставки на веб-странице, MQTT. | TPP2(G2) | да |
| 09 | [Сбор данных 4-20 мА с веб-графиком](09-4-20ma-logger/) - Четыре датчика 4-20 мА: значения в инженерных единицах, график за сутки на веб-странице, CSV и MQTT. | TPP2(G2) | да |
| 10 | [Сторожевой узел: проверка связи и перезагрузка по питанию](10-watchdog/) - Проверяет связь с роутером, камерой или интернетом и перезагружает зависшее устройство по питанию через реле. | TPP2(G2) | да |
| 11 | [Контроллер, с которым говорит нейросеть (MCP)](11-ai-mcp-controller/) - Claude, ChatGPT или локальная модель читают датчики и переключают реле обычными фразами и пишут правила, которые плата выполняет сама. Бета. | LTPP3(G2) | - |
| 12 | [Андон: световая колонна и учёт простоев станка](12-andon/) - Кнопки оператора зажигают световую колонну, контроллер считает минуты работы и простоя, остановки и детали за смену. | TPP2(G2) | да |
| 13 | [Чёрный ящик RS-485: что было на линии перед сбоем](13-rs485-black-box/) - Слушает линию, хранит последние 150 кадров и замораживает снимок при ошибке CRC, исключении Modbus или тишине. | TPP2(G2) | - |
| 14 | [Сварочный пост: учёт времени работы сварщика](14-welding-post/) - По току аппарата считает время дуги, время в работе, зажигания и киловатт-часы за сутки; журнал, CSV и MQTT. | TPP2(G2) | да |
| 15 | [Этикетка по весу на принтер Godex](15-weight-label/) - Весы на RS-232, печать этикетки по стабильному весу на сетевой Godex: масса, даты, весовой EAN-13 и QR. | DS1101 | - |
| 16 | [Подбор по свету с ТСД](16-pick-to-light/) - ТСД сканирует товар, у ячейки загорается лампа, работник подтверждает кнопкой; задание из учётной системы по HTTP. | TPP2(G2) | - |
| 17 | [OSS со своим сервером: MQTT вместо Azure](17-oss-own-server/) - Уличная станция Tibbo OSS отправляет данные на ваш брокер MQTT: графики Grafana, оповещения в Telegram, имитатор станции для проверки. | OSS | - |
| 18 | [Анализатор → ЛИС с буфером](18-lab-analyzer-lis/) - DS1101 принимает результаты анализатора по ASTM, хранит во флеш-памяти и пересылает в ЛИС: ЛИС недоступна - результаты не теряются. | DS1101 | - |
| 19 | [Багажные весы на стойке регистрации](19-checkin-scale/) - Данные весов идут в программу регистрации как раньше, а DS1101 ведёт журнал взвешиваний, отмечает перевес и следит за весами. | DS1101 | - |
| 20 | [Прибор на связи? Serial-over-IP с контролем обмена](20-serial-link-monitor/) - Виртуальный COM-порт, который сам сообщает в syslog, если прибор замолчал или программа отключилась. | DS1101 | - |

## Принципы

- **Самое доступное, что решает задачу.** По умолчанию - плата TPP2(G2) и источник #09 от 12 В; более дорогие блоки - только там, где без них нельзя, и с объяснением в README рецепта.
- **Раскладка, которую одобряет AppBlocks.** Разъёмы выбраны так, чтобы редактор AppBlocks не отмечал сокеты жёлтыми треугольниками: источнику питания #09/#10 - #18, датчику #29 - #00-3. Если документация Tibbo допускает вариант дешевле, но редактор его не принимает, он описан в README рецепта как нишевый.
- **Все настройки объекта в одном файле** `tide/config.tbh`: сеть, MQTT, адреса приборов, пороги.
- **Проверка.** Каждый проект собирается компилятором TIDE без ошибок; варианты AppBlocks собираются компилятором Tibbo, логика изменённых в версии 1.3.0 проектов (04, 08, 10) прогнана на модели по сценариям. Что и как проверено - в строке «Проверка» каждого рецепта. На реальном оборудовании рецепты не проверялись - перед установкой на объект проверьте комплект на стенде.
- **Два варианта - не всегда одно и то же.** Вариант AppBlocks проще варианта TIDE. В каждом рецепте есть список «Чем отличается от варианта TIDE»: прочитайте его до выбора.
- **Рецепт 17 - для станции OSS, а не для платы TPS.** В нём нет проекта TIDE: это сервер в Docker и правка официальной прошивки Tibbo для своего сертификата. Сервер проверен имитатором OSS, изменённая прошивка собирается компилятором Tibbo, на живой OSS рецепт не проверялся.
- **Рецепты 11-13 проверены иначе.** 12 - проект AppBlocks, собран компилятором Tibbo через сборщик AppBlocks; 13 - Tibbo BASIC, собран тем же компилятором, библиотеки лежат в папке проекта; 11 - программа на Python для Linux-платы, 27 автотестов на эмуляторе. Как и остальные, на настоящем железе они не запускались.

## Как начать

1. Установите [TIDE](https://tibbo.ru/downloads), откройте `.tpr` из папки `tide/` нужного рецепта.
2. Поправьте `config.tbh`, соберите (F7), загрузите в контроллер (F5).
3. Для AppBlocks: app.appblocks.io → Import → файл из папки `appblocks/`.

Доработать рецепт словами можно со [скиллами Tibbo для Claude](https://github.com/SCANCODE-IOT/tibbo-claude-skills).

---

# Tibbo recipes: ready-made automation solutions

Twenty automation tasks solved end to end on Tibbo hardware: a TIDE project (Tibbo BASIC), an AppBlocks variant where it fits, a bill of materials, a Tibbit socket layout with power budget and assembly notes. Documentation inside each recipe is in Russian.

| # | Recipe | Board | AppBlocks |
|---|---|---|---|
| 01 | [Modbus RTU → MQTT gateway](01-modbus-rtu-mqtt/) | TPP2(G2) | yes |
| 02 | [Lighting control: relays, web page, schedule](02-lighting/) | TPP2(G2) | yes |
| 03 | [Electricity and water metering](03-metering/) | TPP2(G2) | yes |
| 04 | [Server room monitoring: temperature, humidity, leak](04-server-room/) | TPP2(G2) | yes |
| 05 | [Single-door access control (Wiegand)](05-access-control/) | TPP2(G2) | yes |
| 06 | [Smart serial-over-IP for scales (DS1100)](06-scale-ds1100/) | DS1100 | - |
| 07 | [Remote telemetry over LTE](07-lte-telemetry/) | TPP2(G2) | yes |
| 08 | [Thermostat and ventilation (0-10 V)](08-thermostat-0-10v/) | TPP2(G2) | yes |
| 09 | [4-20 mA data logger with web chart](09-4-20ma-logger/) | TPP2(G2) | yes |
| 10 | [Network watchdog with power-cycle reboot](10-watchdog/) | TPP2(G2) | yes |
| 11 | [A controller that an AI talks to (MCP), beta](11-ai-mcp-controller/) | LTPP3(G2) | - |
| 12 | [Andon: stack light and machine downtime counters](12-andon/) | TPP2(G2) | yes |
| 13 | [RS-485 black box: what was on the bus before a failure](13-rs485-black-box/) | TPP2(G2) | - |
| 14 | [Welding post: welder work time tracking](14-welding-post/) | TPP2(G2) | yes |
| 15 | [Weight label on a Godex printer](15-weight-label/) | DS1101 | - |
| 16 | [Pick-to-light with a mobile computer](16-pick-to-light/) | TPP2(G2) | - |
| 17 | [Tibbo OSS with your own server: MQTT instead of Azure](17-oss-own-server/) | OSS | - |
| 18 | [Lab analyzer → LIS with a flash buffer (ASTM E1381)](18-lab-analyzer-lis/) | DS1101 | - |
| 19 | [Check-in baggage scale: weighing log, overweight, scale health](19-checkin-scale/) | DS1101 | - |
| 20 | [Is the device alive? Serial-over-IP with link monitoring and syslog](20-serial-link-monitor/) | DS1101 | - |

Every project builds with the TIDE compiler with no errors, and AppBlocks variants build with the Tibbo cloud compiler. An AppBlocks variant is simpler than the TIDE one: each recipe lists the differences. Connectors are chosen so that the AppBlocks editor does not flag any socket (power Tibbits #09/#10 use #18, the #29 sensor sits next to #00-3). **Not tested on real hardware** - verify on a bench before deployment. Recipe 17 is for the Tibbo OSS station rather than a TPS board: a Docker server plus a patch to the official Tibbo firmware.

## Versions

- **1.7.0** (2026-11-14): recipes 18-20 for DS1101 device servers in clinics and airports. 18 - ASTM E1381 receiver for a lab analyzer that ACKs each frame only after writing it to a wear-levelled flash ring buffer, then forwards messages to the LIS over TCP with the same protocol; LIS outages, reboots mid-transfer and a full buffer are handled (logic checked on a Python model). 19 - check-in baggage scale: transparent channel for the check-in application plus a weighing log, two overweight limits, zero and link checks, UDP message per bag. 20 - transparent Serial-over-IP that reports a silent device, missing replies or a disconnected application to syslog without storing the traffic. All three build with the Tibbo compiler; not tested on real devices.
- **1.6.0** (2026-11-14): recipe 17 - Tibbo OSS (Outdoor Sensor System) with your own server instead of Azure. The Tibbo Alibaba Cloud firmware gets your CA certificate and port 8883 (patch script and a `.tcu` packer that reproduces official Tibbo releases byte for byte); the server is Docker Compose with Mosquitto (TLS, per-device logins and ACL), Node-RED (time reply, parsing, thresholds, no-data watchdog, Telegram), InfluxDB 2 and Grafana. Server checked with an OSS simulator; the patched firmware builds with the Tibbo compiler; not tested on a real OSS.
- **1.5.1** (2026-11-13): fixes after an independent code review. Web pages of recipes 02, 03, 04, 05, 08, 09, 10, 13, 14, 15, 16: the first query parameter was not found because the TiOS request string has no leading "?" - buttons, settings and the clock set from the page could fail. Recipe 06: values on the page are sent as TiOS documentation requires. Recipe 15: the print button got no reply (it went to the printer socket), QR in alphanumeric mode, weight without float rounding, stuck printer connection reset, EZPL control characters removed from the product name. Recipe 16: no lost first parameter, longer request buffer, full journal events, CSV-safe codes and names.
- **1.5.0** (2026-11-13): recipes 15 and 16 for warehouses and labelling. 15 - a scale on RS-232 and a network Godex printer (EZPL over TCP 9100): the label is printed when the weight is stable, with net weight, packing and best-before dates, a weight EAN-13 and a QR code; printer status is checked with ~S,CHECK. 16 - pick-to-light: a CipherLab, Point Mobile or other Android mobile computer scans in keyboard mode on the controller's web page, the cell lamp lights (#11), the worker confirms with the cell button (#04-8); tasks come from the accounting system over HTTP. Both built with the Tibbo compiler, logic checked on a model.
- **1.4.0** (2026-11-13): recipe 14 - welding post time tracking. A current switch on the welder supply cable and an isolated 24 V input (#04-5) detect the arc; the controller counts arc time, work time, arc starts and energy per day (Modbus meter), keeps a 62-day journal, CSV and MQTT. TIDE and AppBlocks variants, built with the Tibbo compiler, logic checked on a model.
- **1.3.0** (2026-11-13): audit of all recipes against their descriptions. AppBlocks variants: 10 - long pause after several power cycles in a row (was only in TIDE); 04 - alarm code no longer flaps every second (it flooded MQTT), threshold delay, inputs 3 and 4, sensor-loss debounce; 08 - one missed sensor reply no longer switches heating off; 05 - web console password; 01, 03 - sane network defaults instead of template values. TIDE: 07 - the overheat flag now returns to 0; 09 - values above 327.67 units were clipped in the chart, CSV and MQTT. Every README now lists how the AppBlocks variant differs from the TIDE one and has a version history.
- **1.2.0** (2026-11-10): three new recipes. 11 - an MCP server on the Linux board LTPP3(G2): an AI reads sensors, switches relays and writes rules (Python, 27 tests on a board emulator, beta). 12 - Andon, an AppBlocks project built with the Tibbo compiler through the AppBlocks builder. 13 - RS-485 black box in Tibbo BASIC, built with the same compiler; frame splitting checked on a model. None of them has run on real hardware yet.
- **1.1.0** (2026-10-26): recipes 02-05 - inputs of #54 on #21 in S10 and the #09 supply on #18 in S12 instead of one #20 (the AppBlocks editor accepts only #18 for power Tibbits); recipe 07 - #00-3 in S11 powers the #29 sensor; recipe 09 - #12 moved to S9; exact terminal numbers in the READMEs.
- **1.0.1**: UART divider without overflow on 16-bit DS1100 (recipe 06), library timer period in recipe 03.
- **1.0**: first release.

## License

MIT - see [LICENSE](LICENSE). Prepared by Scancode (OOO SK-Trade), official Tibbo Technology distributor. Contact: iot@scancode.ru, https://tibbo.ru/contacts
