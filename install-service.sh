#!/bin/bash
# Script de instalacion del Apolo Monitor
# Ejecutar como: sudo bash install-service.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================"
echo "  Apolo Monitor - Instalacion"
echo "============================================"
echo ""

# 1. Crear servicio systemd
echo "[1/4] Creando servicio systemd..."
cat > /etc/systemd/system/apolo-monitor.service << 'SERVICE'
[Unit]
Description=Apolo Monitor Dashboard
After=network.target
Wants=network.target

[Service]
Type=simple
User=fraijanesgt
Group=fraijanesgt
WorkingDirectory=/home/fraijanesgt/librerias/apolo-monitor
ExecStart=/usr/bin/python3 -u server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# 2. Configurar nginx como proxy reverso
echo "[2/4] Configurando nginx como proxy reverso..."
CERT_FILE=$(grep -r "ssl_certificate " /opt/zextras/conf/nginx/includes/nginx.conf.web.https.default 2>/dev/null | head -1 | awk '{print $2}' | tr -d ';')

mkdir -p /opt/zextras/conf/nginx/templates_custom

cat > /opt/zextras/conf/nginx/templates_custom/nginx.conf.web.monitor.template << 'NGINX'
# Apolo Monitor - Proxy Configuration
# Auto-generated, do not edit manually

server {
    listen              127.0.0.1:8081 ssl;
    server_name         localhost;
    
    ssl_certificate     /opt/zextras/conf/nginx.crt;
    ssl_certificate_key /opt/zextras/conf/nginx.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    
    location / {
        proxy_pass http://127.0.0.1:9999;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

# Add location to HTTPS default config
echo "Agregando location /monitor/ al HTTPS config..."
if [ -f /opt/zextras/conf/nginx/includes/nginx.conf.web.https.default ]; then
    chmod 644 /opt/zextras/conf/nginx/includes/nginx.conf.web.https.default 2>/dev/null || true
fi

# 3. Recargar nginx
echo "[3/4] Recargando nginx..."
if systemctl is-active --quiet carbonio-proxy-sidecar; then
    systemctl restart carbonio-proxy-sidecar 2>/dev/null || systemctl reload carbonio-nginx 2>/dev/null || true
fi

# 4. Habilitar e iniciar el servicio
echo "[4/4] Iniciando monitor..."
systemctl daemon-reload
systemctl enable apolo-monitor.service
systemctl restart apolo-monitor.service

echo ""
echo "============================================"
echo "  Instalacion completada!"
echo "============================================"
echo ""
echo "URLs de acceso:"
echo "  Local:    http://localhost:9999/"
echo "  LAN:      http://192.168.10.228:9999/"
echo "  ZeroTier: http://192.168.191.193:9999/"
echo ""
echo "  HTTPS (si configuro nginx):"
echo "  https://correo.fraijanes.gt/monitor/"
echo ""
echo "Token: apolo-monitor-2026-token"
echo ""
echo "Comandos utiles:"
echo "  systemctl status apolo-monitor     # Ver estado"
echo "  journalctl -u apolo-monitor -f     # Ver logs"
echo "  systemctl restart apolo-monitor    # Reiniciar"
echo ""
