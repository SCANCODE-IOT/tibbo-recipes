#!/bin/sh
# Установка стенда на LTPP3(G2). Запускать на плате от root из распакованного архива:
#   sh deploy/install.sh
# Скиллы (для проверки плат и кода) ожидаются в /opt/tibbo-ai-skills.
set -e
DEST=/opt/tibbo-stand
python3 -c 'import sys; assert sys.version_info >= (3, 9), sys.version' || { echo "Нужен Python 3.9+"; exit 1; }
mkdir -p "$DEST"
cp -r tibbo_mcp tools deploy config.example.json config.cloud.example.json config.hub.example.json README.md README.ru.md "$DEST"/
if [ ! -f "$DEST/config.json" ]; then
  sed -e 's/"board": "sim"/"board": "ltpp3g2"/' \
      -e 's#"skills_dir": "../tibbo-ai-skills/skills"#"skills_dir": "/opt/tibbo-ai-skills/skills"#' \
      config.example.json > "$DEST/config.json"
  echo "Создан $DEST/config.json - проверьте адрес нейросети, шины I2C и линии (python3 -m tibbo_mcp --probe)"
fi
cp deploy/tibbo-stand.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable tibbo-stand
systemctl restart tibbo-stand
sleep 2
systemctl --no-pager status tibbo-stand | head -5
echo "Панель: http://$(hostname -I | awk '{print $1}'):8080/"
