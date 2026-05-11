#!/bin/bash
# Configurar nginx de Carbonio para servir /monitor/ en https://correo.fraijanes.gt/monitor/
# Ejecutar: sudo bash setup-nginx.sh

set -e

echo "============================================"
echo "  Configurando proxy /monitor/ en nginx..."
echo "============================================"
echo ""

# 1. Crear archivo de configuracion para el monitor
echo "[1/4] Creando archivo de configuracion nginx..."
cat > /opt/zextras/conf/nginx/includes/nginx.conf.monitor << 'CONF'
# Carbonio Email Monitor - Proxy Configuration
location ^~ /monitor/ {
    proxy_pass http://127.0.0.1:9999/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 90s;
    proxy_buffering off;
}
CONF

chown zextras:zextras /opt/zextras/conf/nginx/includes/nginx.conf.monitor
echo "  -> /opt/zextras/conf/nginx/includes/nginx.conf.monitor"

# 2. Agregar include al archivo de configuracion HTTPS por defecto
echo "[2/4] Agregando include al HTTPS config..."
HTTPS_FILE="/opt/zextras/conf/nginx/includes/nginx.conf.web.https.default"

if ! grep -q "nginx.conf.monitor" "$HTTPS_FILE" 2>/dev/null; then
    # Insertar el include antes del ultimo '}'
    sed -i '$i\    include /opt/zextras/conf/nginx/includes/nginx.conf.monitor;' "$HTTPS_FILE"
    echo "  -> Include agregado a $HTTPS_FILE"
else
    echo "  -> El include ya existe"
fi

# 3. Verificar la configuracion de nginx
echo "[3/4] Verificando configuracion de nginx..."
/opt/zextras/common/sbin/nginx -t -c /opt/zextras/conf/nginx.conf
echo "  -> Configuracion OK"

# 4. Recargar nginx
echo "[4/4] Recargando nginx..."
/opt/zextras/common/sbin/nginx -s reload -c /opt/zextras/conf/nginx.conf
echo "  -> Nginx recargado exitosamente"

echo ""
echo "============================================"
echo "  Configuracion completada!"
echo "============================================"
echo ""
echo "  URL: https://correo.fraijanes.gt/monitor/"
echo "  Token: carbonio-monitor-2026-token"
echo ""
echo "  Prueba: curl -k https://correo.fraijanes.gt/monitor/api/v1/health?token=carbonio-monitor-2026-token"
echo ""
