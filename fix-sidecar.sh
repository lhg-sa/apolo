#!/bin/bash
# Reparar sidecars de Consul/Carbonio
# Ejecutar: sudo bash fix-sidecar.sh

set -e

echo "============================================"
echo "  Reparando sidecars de Consul..."
echo "============================================"

# 1. Obtener un token existente (funciona como ejemplo)
TOKEN_SRC=""
for f in /etc/carbonio/clamav/service-discover/token /etc/carbonio/mailbox/service-discover/token /etc/carbonio/files/service-discover/token; do
    if [ -f "$f" ]; then
        TOKEN_SRC="$f"
        echo "Token de referencia: $f"
        break
    fi
done

# 2. Crear directorios para los tokens faltantes
mkdir -p /etc/carbonio/mailbox-admin/service-discover
mkdir -p /etc/carbonio/mailbox-nslookup/service-discover

# 3. Generar tokens via consul ACL (si es posible)
if [ -n "$TOKEN_SRC" ]; then
    echo "Creando tokens via Consul API..."
    
    # Policy files already exist, just need tokens
    # Use consul to create service tokens
    for service in carbonio-mailbox-admin carbonio-mailbox-nslookup; do
        echo "  Generando token para $service..."
        /usr/bin/consul acl token create \
            -service-identity="$service" \
            -description="sidecar token for $service" \
            -format json 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    t=d.get('SecretID','')
    if t:
        with open('/etc/carbonio/$service/service-discover/token','w') as f:
            f.write(t)
        print(f'    Token creado: {t[:20]}...')
except: print('    Error generando token')
" 2>/dev/null || echo "    No se pudo generar token (sin permisos ACL)"
    done
fi

# 4. Workaround: si no se pudieron crear tokens, configurar sin sidecar
if [ ! -f /etc/carbonio/mailbox-admin/service-discover/token ] || [ ! -s /etc/carbonio/mailbox-admin/service-discover/token ]; then
    echo ""
    echo "No se pudieron generar tokens. Configurando modo directo..."
    echo ""
    echo "Para que zmprov funcione SIN sidecar, modifica:"
    echo "/etc/zextras/service-discover/carbonio-mailbox-admin.hcl"
    echo "y elimina el bloque 'connect { sidecar_service { ... } }'"
    echo ""
    echo "O simplemente reinicia los servicios asi:"
    echo "  sudo systemctl restart carbonio-mailbox-sidecar"
fi

# 5. Dar permisos correctos
if [ -f /etc/carbonio/mailbox-admin/service-discover/token ]; then
    chown root:root /etc/carbonio/mailbox-admin/service-discover/token 2>/dev/null || true
    chmod 644 /etc/carbonio/mailbox-admin/service-discover/token 2>/dev/null || true
fi
if [ -f /etc/carbonio/mailbox-nslookup/service-discover/token ]; then
    chown root:root /etc/carbonio/mailbox-nslookup/service-discover/token 2>/dev/null || true
    chmod 644 /etc/carbonio/mailbox-nslookup/service-discover/token 2>/dev/null || true
fi

# 6. Intentar reiniciar sidecars
echo ""
echo "Reiniciando servicios..."
sudo systemctl restart carbonio-mailbox-admin-sidecar 2>/dev/null && echo "  mail-admin OK" || echo "  mail-admin FAIL"
sudo systemctl restart carbonio-mailbox-nslookup-sidecar 2>/dev/null && echo "  mail-nslookup OK" || echo "  mail-nslookup FAIL"

echo ""
echo "============================================"
echo "  Verificacion:"
echo "============================================"
echo "  /opt/zextras/bin/zmprov -z ga oarana@munifraijanes.gob.gt zimbraAccountStatus"
echo ""
