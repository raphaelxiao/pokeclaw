#!/bin/bash

# Load PI_USER from .env if it exists, default to 'pi'
PI_USER="pi"
if [ -f .env ]; then
  # Extract PI_USER from .env handling potential quotes
  ENV_USER=$(grep -E '^[ \t]*export[ \t]+PI_USER=' .env | sed -E 's/.*PI_USER="?([^"]*)"?.*/\1/')
  if [ -n "$ENV_USER" ]; then
    PI_USER="$ENV_USER"
  fi
fi

TARGET_HOST="${PI_USER}@pizero.local"
TARGET_DIR="/home/${PI_USER}/pokeclaw"

rsync -avz --delete --exclude='__pycache__' --exclude='.lgd-*' ./ ${TARGET_HOST}:${TARGET_DIR}/ &&
ssh ${TARGET_HOST} "
  sed -i 's|^User=.*|User='${PI_USER}'|' ${TARGET_DIR}/pokeclaw.service &&
  sed -i 's|^WorkingDirectory=.*|WorkingDirectory='${TARGET_DIR}'|' ${TARGET_DIR}/pokeclaw.service &&
  sed -i 's|^EnvironmentFile=.*|EnvironmentFile='${TARGET_DIR}/.env|' ${TARGET_DIR}/pokeclaw.service &&
  sudo cp ${TARGET_DIR}/pokeclaw.service /etc/systemd/system/ &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable pokeclaw &&
  sudo systemctl restart pokeclaw &&
  sleep 2 &&
  sudo journalctl -u pokeclaw -n 30 --no-pager
"
