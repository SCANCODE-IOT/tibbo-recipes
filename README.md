# Рецепты Tibbo: готовые решения автоматизации

Десять типовых задач, решённых от начала до конца на оборудовании [Tibbo Technology](https://tibbo.com): проект TIDE на Tibbo BASIC, вариант для [AppBlocks](https://appblocks.io), спецификация (`bom.csv`), раскладка Tibbit по сокетам с бюджетом питания и инструкция по сборке и настройке.

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

## Принципы

- **Самое доступное, что решает задачу.** По умолчанию - плата TPP2(G2) и источник #09 от 12 В; более дорогие блоки - только там, где без них нельзя, и с объяснением в README рецепта.
- **Все настройки объекта в одном файле** `tide/config.tbh`: сеть, MQTT, адреса приборов, пороги.
- **Проверка.** Каждый проект собирается в TIDE (библиотеки 2_01_05) без ошибок и предупреждений; варианты AppBlocks открываются в редакторе без ошибок и собираются облачным компилятором. На реальном оборудовании рецепты не проверялись - перед установкой на объект проверьте комплект на стенде.

## Как начать

1. Установите [TIDE](https://tibbo.ru/downloads), откройте `.tpr` из папки `tide/` нужного рецепта.
2. Поправьте `config.tbh`, соберите (F7), загрузите в контроллер (F5).
3. Для AppBlocks: app.appblocks.io → Import → файл из папки `appblocks/`.

Доработать рецепт словами можно со [скиллами Tibbo для Claude](https://github.com/SCANCODE-IOT/tibbo-claude-skills).

---

# Tibbo recipes: ready-made automation solutions

Ten typical automation tasks solved end to end on Tibbo hardware: a TIDE project (Tibbo BASIC), an AppBlocks variant, a bill of materials, a Tibbit socket layout with power budget and assembly notes. Documentation inside each recipe is in Russian.

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

Every project builds in TIDE (libraries 2_01_05) with no errors or warnings, and AppBlocks variants open without errors and build in the cloud. **Not tested on real hardware** - verify on a bench before deployment.

## License

MIT - see [LICENSE](LICENSE). Prepared by Scancode (OOO SK-Trade), official Tibbo Technology distributor in Russia and CIS. Contact: iot@scancode.ru, https://tibbo.ru/contacts
