# Apolo Monitor — Despliegue en nuevo servidor

## Requisitos

- Ubuntu 20.04+ con Carbonio CE (Postfix, LDAP operativo)
- Python 3.8+ (stdlib — **no requiere pip**)
- Usuario no-root con sudo (ej: `admin` o `fraijanesgt`)
- Acceso LDAP: `uid=zimbra,cn=admins,cn=zimbra` (password vía `su - zimbra -c 'zmlocalconfig -s zimbra_ldap_password'`)
- Archivos fuente del monitor (los 5 `.py` + `static/index.html`)

---

## Paso 1: Preparar directorio

```bash
mkdir -p /home/<USUARIO>/apolo-monitor/static
chmod 755 /home/<USUARIO>/apolo-monitor /home/<USUARIO>/apolo-monitor/static
```

## Paso 2: Copiar archivos

```
apolo-monitor/
  server.py            ← Servidor HTTP (API + dashboard)
  log_parser.py        ← Parseo de /var/log/mail.log
  metrics_db.py        ← SQLite + consultas + LDAP
  system_monitor.py    ← CPU/RAM/disco/red/servicios + bloqueo iptables
  alerts.py            ← Motor de alertas
  static/
    index.html         ← Frontend (Chart.js vía CDN)
  monitor.db           ← SQLite DB (se crea sola al iniciar)
```

```bash
# Desde el servidor origen:
rsync -avz apolo-monitor/ usuario@nuevo-servidor:/home/usuario/apolo-monitor/
```

## Paso 3: Configurar variables por servidor

### 3a. En `server.py`

| Variable | Descripción | Cambiar |
|---|---|---|
| `API_TOKEN` | Token de acceso | Opcional (cualquier string) |
| `HOST` = `'0.0.0.0'` | IP donde escucha | No tocar (nginx proxy) |
| `PORT` = `9999` | Puerto local | Opcional |

### 3b. En `metrics_db.py`

| Variable | Descripción | Ejemplo nuevo servidor |
|---|---|---|
| `LDAP_HOST` | IP/nombre del servidor LDAP | `'mail.nuevodominio.gt'` |
| `LDAP_PASSWORD` | Password de zimbra LDAP | `'password_del_nuevo_servidor'` |
| `DB_PATH` | Ruta a SQLite | No tocar |

Obtener password LDAP en el nuevo servidor:
```bash
su - zimbra -c 'zmlocalconfig -s zimbra_ldap_password'
```

### 3c. En `log_parser.py`

| Variable | Descripción |
|---|---|
| `LOG_FILES` | Rutas a mail.log (default `/var/log/mail.log`) |

### 3d. En `system_monitor.py`

| Variable | Descripción |
|---|---|
| `CARBONIO_SERVICES` | Lista de servicios Carbonio a monitorear |

### 3e. Zona horaria

Guatemala UTC-6: el servidor usa UTC y el frontend/backend restan 21600s.
Para otra zona horaria, cambiar en:
- `server.py` → remove `_dt.utcfromtimestamp(ts - 21600)` (backend)
- `static/index.html` → `Date.now() - 21600000` y `(ts - 21600) * 1000` (frontend)

---

## Paso 4: Systemd service

Crear `/etc/systemd/system/apolo-monitor.service`:

```ini
[Unit]
Description=Apolo Monitor (para Carbonio)
After=network.target postfix.service

[Service]
Type=simple
User=<USUARIO>
Group=<USUARIO>
WorkingDirectory=/home/<USUARIO>/apolo-monitor
ExecStart=/usr/bin/python3 -u server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now apolo-monitor
sudo journalctl -u apolo-monitor -f
```

---

## Paso 5: Nginx reverse proxy (Carbonio)

Crear `/opt/zextras/conf/nginx/includes/nginx.conf.monitor`:

```nginx
location ^~ /monitor/ {
    proxy_pass http://127.0.0.1:9999;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 30s;
}
```

Agregar dentro del bloque `server { }` en
`/opt/zextras/conf/nginx/includes/nginx.conf.web.https.default`:

```nginx
include /opt/zextras/conf/nginx/includes/nginx.conf.monitor;
```

Recargar nginx:

```bash
sudo /opt/zextras/common/sbin/nginx -s reload -c /opt/zextras/conf/nginx.conf
```

> **Importante**: Carbonio `zmconfigd` regenera archivos de nginx al reiniciar servicios.
> Si se pierde el include, re-agregarlo a `nginx.conf.web.https.default`.

---

## Paso 6: Verificar funcionamiento

```bash
# Health check (sin token)
curl http://localhost:9999/api/v1/health

# API con token
curl "http://localhost:9999/api/v1/stats/summary?token=<TOKEN>"

# Frontend via nginx
curl -k https://correo.dominio.gt/monitor/
```

---

## Paso 7: IP Blocking (iptables)

El monitor crea automáticamente la cadena `MONITOR_BLOCK` y la inserta en `INPUT`.
No requiere configuración manual. Verificar:

```bash
sudo iptables -L MONITOR_BLOCK -n
```

Las IPs bloqueadas desde el dashboard persisten en iptables hasta reinicio del servidor.
Para hacerlas persistentes:

```bash
# Debian/Ubuntu
sudo iptables-save > /etc/iptables/rules.v4
```

---

## Resumen de personalización por servidor

| Estado | Variable | Archivo |
|---|---|---|
| Activo | `API_TOKEN` | `server.py` |
| Activo | Puerto | `server.py: PORT` |
| Activo | LDAP host | `metrics_db.py: LDAP_HOST` |
| Activo | LDAP password | `metrics_db.py: LDAP_PASSWORD` |
| Default | Log de correo | `log_parser.py: LOG_FILES` |
| Default | Servicios monitoreados | `system_monitor.py: CARBONIO_SERVICES` |
| Default | Zona horaria | `server.py` + `index.html` (Guatemala = -21600s) |

---

## Diagnóstico de problemas comunes

| Problema | Causa | Solución |
|---|---|---|
| `parsed_events: 0` | Parseo inicial lento (intervalo 5 min) | Esperar, o llamar `/api/v1/monitor/parse` |
| LDAP no conecta | `LDAP_HOST`/`LDAP_PASSWORD` incorrectos | Verificar con `zmlocalconfig` |
| zmprov falla | Consul sidecar sin token | Usar `ldapmodify` directo (ya implementado) |
| DB corrupta | Corte de energía | Detener servicio, borrar `monitor.db`, reiniciar |
| iptables: Permission denied | Usuario sin sudo | Agregar a sudoers o ejecutar como root |

---

## Actualizar desde versión anterior

```bash
cd /home/<USUARIO>/apolo-monitor
# Respaldar DB
cp monitor.db monitor.db.bak
# Reemplazar archivos (NO borrar monitor.db)
cp /tmp/nuevos-archivos/*.py .
cp /tmp/nuevos-archivos/static/index.html static/
# Reiniciar
sudo systemctl restart apolo-monitor
```

---

## Logs

```bash
sudo journalctl -u apolo-monitor -f
```

## Logs de nginx (proxy)

```bash
sudo journalctl -u nginx -f   # o
tail -f /opt/zextras/log/nginx/access.log
```
