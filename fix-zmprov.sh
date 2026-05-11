#!/bin/bash
# Reparar zmprov - deshabilitar sidecar proxy para mailbox-admin
# Ejecutar: sudo bash fix-zmprov.sh

set -e

echo "============================================"
echo "  Reparando zmprov (bypass sidecar Consul)"
echo "============================================"
echo ""

# Hacer backup y modificar config para eliminar sidecar
for service in carbonio-mailbox-admin carbonio-mailbox-nslookup; do
    FILE="/etc/zextras/service-discover/${service}.hcl"
    BACKUP="${FILE}.bak.$(date +%s)"
    
    if [ -f "$FILE" ]; then
        echo "[$service]"
        cp "$FILE" "$BACKUP"
        echo "  Backup: $BACKUP"
        
        # Eliminar el bloque connect/sidecar_service del archivo
        sed -i '/^  connect {/,${
            /^  connect {/,/^  }/{
                /^  }/{
                    /^  }/d
                }
                /^  connect {/d
            }
        }' "$FILE" 2>/dev/null || {
            # Si el sed anterior falla, usar metodo alternativo
            python3 -c "
import re
with open('$FILE') as f: c = f.read()
c = re.sub(r'\s*connect\s*\{[^}]*sidecar_service[^}]*\}', '', c, flags=re.DOTALL)
with open('$FILE','w') as f: f.write(c)
print('  Sidecar eliminado')
"
        }
        echo "  Config limpia"
    fi
done

echo ""
echo "Recargando configuracion Consul..."
consul reload 2>/dev/null || echo "  (recarga manual no necesaria)"

echo ""
echo "Probando zmprov..."
/opt/zextras/bin/zmprov -z ga oarana@munifraijanes.gob.gt zimbraAccountStatus 2>&1 | grep -v SLF4J | grep -v "Class path" | grep -v "Found binding" | grep -v "Actual binding" | grep -v "http://www.slf4j" | head -5

echo ""
echo "Si aun falla, reinicia el servidor:"
echo "  sudo reboot"
echo ""
