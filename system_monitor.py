import os
import time
import subprocess
import re

CARBONIO_SERVICES = [
    'carbonio-mailbox', 'carbonio-mta-sidecar', 'carbonio-message-broker',
    'carbonio-message-dispatcher', 'carbonio-files', 'carbonio-preview',
    'carbonio-storages', 'carbonio-tasks', 'carbonio-user-management',
    'carbonio-ws-collaboration', 'carbonio-proxy-sidecar',
    'carbonio-docs-connector', 'carbonio-docs-editor',
    'carbonio-clamav-sidecar', 'carbonio-videoserver',
    'carbonio-prometheus-node-exporter'
]

PREV_CPU = {}
PREV_NET = {}
PREV_TIME = time.time()

def get_cpu_percent():
    global PREV_CPU, PREV_TIME
    try:
        with open('/proc/stat', 'r') as f:
            line = f.readline()
        parts = line.strip().split()
        if parts[0] != 'cpu' or len(parts) < 5:
            return 0.0
        user = int(parts[1])
        nice = int(parts[2])
        system = int(parts[3])
        idle = int(parts[4])
        iowait = int(parts[5]) if len(parts) > 5 else 0
        irq = int(parts[6]) if len(parts) > 6 else 0
        softirq = int(parts[7]) if len(parts) > 7 else 0
        steal = int(parts[8]) if len(parts) > 8 else 0
        total = user + nice + system + idle + iowait + irq + softirq + steal
        active = total - idle
        now = time.time()
        if PREV_CPU:
            dt = now - PREV_TIME
            if dt > 0:
                total_d = total - PREV_CPU.get('total', total)
                active_d = active - PREV_CPU.get('active', active)
                if total_d > 0:
                    pct = (active_d / total_d) * 100.0
                    PREV_CPU = {'total': total, 'active': active}
                    PREV_TIME = now
                    return round(pct, 1)
        PREV_CPU = {'total': total, 'active': active}
        PREV_TIME = now
        return 0.0
    except:
        return 0.0

def get_memory_info():
    try:
        with open('/proc/meminfo', 'r') as f:
            data = f.read()
        mem = {}
        for line in data.split('\n'):
            m = re.match(r'^(\w+):\s+(\d+)', line)
            if m:
                mem[m.group(1)] = int(m.group(2))
        total = mem.get('MemTotal', 0)
        free = mem.get('MemFree', 0)
        buffers = mem.get('Buffers', 0)
        cached = mem.get('Cached', 0)
        available = mem.get('MemAvailable', 0)
        used = total - free - buffers - cached
        if total == 0:
            return {'total_mb': 0, 'used_mb': 0, 'free_mb': 0, 'available_mb': 0, 'percent': 0}
        return {
            'total_mb': round(total / 1024, 1),
            'used_mb': round(used / 1024, 1),
            'free_mb': round(free / 1024, 1),
            'available_mb': round(available / 1024, 1),
            'percent': round(((total - available) / total) * 100, 1)
        }
    except:
        return {'total_mb': 0, 'used_mb': 0, 'free_mb': 0, 'available_mb': 0, 'percent': 0}

def get_swap_info():
    try:
        with open('/proc/meminfo', 'r') as f:
            data = f.read()
        total = 0
        free = 0
        for line in data.split('\n'):
            if line.startswith('SwapTotal:'):
                total = int(line.split()[1])
            elif line.startswith('SwapFree:'):
                free = int(line.split()[1])
        if total == 0:
            return {'total_mb': 0, 'used_mb': 0, 'percent': 0}
        return {
            'total_mb': round(total / 1024, 1),
            'used_mb': round((total - free) / 1024, 1),
            'percent': round(((total - free) / total) * 100, 1)
        }
    except:
        return {'total_mb': 0, 'used_mb': 0, 'percent': 0}

def get_disk_info():
    try:
        result = subprocess.run(['df', '-B1', '--exclude-type=tmpfs', '--exclude-type=devtmpfs'],
                               capture_output=True, text=True, timeout=5)
        mounts = []
        lines = result.stdout.strip().split('\n')[1:]
        for line in lines:
            parts = line.split()
            if len(parts) >= 6:
                total = int(parts[1])
                used = int(parts[2])
                avail = int(parts[3])
                pct = parts[4].replace('%', '')
                mount = parts[5]
                try:
                    pct_val = float(pct)
                except:
                    pct_val = 0.0
                mounts.append({
                    'filesystem': parts[0],
                    'mount': mount,
                    'total_gb': round(total / (1024**3), 1),
                    'used_gb': round(used / (1024**3), 1),
                    'available_gb': round(avail / (1024**3), 1),
                    'percent': pct_val
                })
        return mounts
    except:
        return []

def get_network_io():
    global PREV_NET, PREV_TIME
    try:
        with open('/proc/net/dev', 'r') as f:
            lines = f.readlines()[2:]
        interfaces = {}
        now = time.time()
        dt = now - PREV_TIME if PREV_TIME > 0 else 1
        if dt <= 0:
            dt = 1
        total_rx = 0
        total_tx = 0
        for line in lines:
            parts = line.strip().split()
            iface = parts[0].rstrip(':')
            if iface == 'lo':
                continue
            rx_bytes = int(parts[1])
            tx_bytes = int(parts[9])
            total_rx += rx_bytes
            total_tx += tx_bytes
            rx_speed = 0
            tx_speed = 0
            if iface in PREV_NET:
                rx_speed = max(0, (rx_bytes - PREV_NET[iface]['rx']) / dt)
                tx_speed = max(0, (tx_bytes - PREV_NET[iface]['tx']) / dt)
            PREV_NET[iface] = {'rx': rx_bytes, 'tx': tx_bytes}
            interfaces[iface] = {
                'rx_bytes': rx_bytes,
                'tx_bytes': tx_bytes,
                'rx_speed': round(rx_speed, 0),
                'tx_speed': round(tx_speed, 0)
            }
        total_rx_speed = 0
        total_tx_speed = 0
        if '_total' in PREV_NET:
            total_rx_speed = max(0, (total_rx - PREV_NET['_total']['rx']) / dt)
            total_tx_speed = max(0, (total_tx - PREV_NET['_total']['tx']) / dt)
        PREV_NET['_total'] = {'rx': total_rx, 'tx': total_tx}
        return {
            'interfaces': interfaces,
            'total_rx_bytes': total_rx,
            'total_tx_bytes': total_tx,
            'total_rx_speed': round(total_rx_speed, 0),
            'total_tx_speed': round(total_tx_speed, 0)
        }
    except:
        return {'interfaces': {}, 'total_rx_bytes': 0, 'total_tx_bytes': 0,
                'total_rx_speed': 0, 'total_tx_speed': 0}

def get_system_load():
    try:
        with open('/proc/loadavg', 'r') as f:
            parts = f.read().strip().split()
        return {
            'load_1m': float(parts[0]),
            'load_5m': float(parts[1]),
            'load_15m': float(parts[2]),
            'procs_running': int(parts[3].split('/')[0]),
            'procs_total': int(parts[3].split('/')[1])
        }
    except:
        return {'load_1m': 0, 'load_5m': 0, 'load_15m': 0, 'procs_running': 0, 'procs_total': 0}

def get_uptime():
    try:
        with open('/proc/uptime', 'r') as f:
            parts = f.read().strip().split()
        seconds = float(parts[0])
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        return {'uptime_seconds': seconds, 'uptime_str': f'{days}d {hours}h {minutes}m'}
    except:
        return {'uptime_seconds': 0, 'uptime_str': 'N/A'}

def get_carbonio_services():
    status_map = {}
    for svc in CARBONIO_SERVICES:
        try:
            r = subprocess.run(['systemctl', 'is-active', svc],
                              capture_output=True, text=True, timeout=5)
            status = r.stdout.strip()
            status_map[svc] = status
        except:
            status_map[svc] = 'unknown'
    total = len(status_map)
    active = sum(1 for s in status_map.values() if s == 'active')
    return {
        'services': status_map,
        'total': total,
        'active': active,
        'inactive': total - active
    }

def get_recent_auth_log(limit=20):
    entries = []
    auth_files = ['/var/log/auth.log', '/var/log/auth.log.1']
    exclude_patterns = [
        'apolo-monitor', 'postqueue', 'postsuper', 'ldapsearch', 'ldapmodify',
        'systemctl.*apolo-monitor', 'journalctl.*carbonio', 'cat > /etc/systemd',
        'COMMAND:.*postqueue', 'COMMAND:.*postsuper', 'COMMAND:.*ldap',
        'COMMAND:.*apolo-monitor', 'COMMAND:.*systemctl.*apolo-monitor',
        'opencode', 'apolo-monitor', 'COMMAND:.*/usr/bin/bash.*systemctl'
    ]
    for fp in auth_files:
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, 'r', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    skip = False
                    for pat in exclude_patterns:
                        if pat in line:
                            skip = True
                            break
                    if skip:
                        continue
                    if 'sshd' in line:
                        entry = _parse_auth_line(line)
                        if entry:
                            entries.append(entry)
                    elif 'sudo' in line:
                        entry = _parse_auth_line(line)
                        if entry:
                            entries.append(entry)
        except:
            continue
    entries.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    return entries[:limit]

def _parse_auth_line(line):
    try:
        parts = line.split()
        if len(parts) < 5:
            return None
        month = parts[0]
        day = parts[1]
        time_part = parts[2]
        host = parts[3]
        proc = parts[4].rstrip(':')
        msg = ' '.join(parts[5:])
        ts = _parse_syslog_ts(month, day, time_part)
        if not ts:
            return None
        entry_type = 'ssh'
        user = ''
        ip = ''
        status = 'info'
        if 'Failed password' in msg:
            status = 'failed'
            m = re.search(r'Failed password for (?:invalid user )?(\S+) from (\S+)', msg)
            if m:
                user = m.group(1)
                ip = m.group(2)
        elif 'Accepted password' in msg or 'Accepted publickey' in msg:
            status = 'success'
            m = re.search(r'Accepted (?:password|publickey) for (\S+) from (\S+)', msg)
            if m:
                user = m.group(1)
                ip = m.group(2)
        elif 'session opened' in msg:
            status = 'session'
            m = re.search(r'for user (\S+)', msg)
            if m:
                user = m.group(1)
        elif 'Invalid user' in msg:
            status = 'invalid_user'
            m = re.search(r'Invalid user (\S+) from (\S+)', msg)
            if m:
                user = m.group(1)
                ip = m.group(2)
        elif 'sudo' in proc.lower():
            entry_type = 'sudo'
            if 'COMMAND=' in msg:
                m = re.search(r'(\S+)\s*:.*COMMAND=(.*)', msg)
                if m:
                    user = m.group(1)
                    msg = 'COMMAND: ' + m.group(2)
        from datetime import datetime as _dt
        gt_dt = _dt.utcfromtimestamp(ts - 21600) if ts else None
        gt_str = gt_dt.strftime('%b %d %H:%M:%S') if gt_dt else f'{month} {day} {time_part}'
        return {
            'timestamp': ts,
            'datetime': gt_str,
            'type': entry_type,
            'user': user,
            'ip': ip,
            'status': status,
            'message': msg[:200]
        }
    except:
        return None

def _parse_syslog_ts(month, day, time_part):
    import time as t_module
    from datetime import datetime
    MONTHS = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
              'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
    mo = MONTHS.get(month, 1)
    da = int(day) if day.isdigit() else 0
    now = datetime.fromtimestamp(t_module.time())
    year = now.year
    if mo > now.month and now.month == 12:
        year -= 1
    try:
        hp = time_part.split(':')
        dt = datetime(year, mo, da, int(hp[0]), int(hp[1]), int(hp[2]))
        return dt.timestamp()
    except:
        return None

def get_queue_count():
    try:
        r = subprocess.run(['postqueue', '-p'], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            count = len([l for l in r.stdout.split('\n') if re.match(r'^[A-F0-9]', l)])
            return count
        return 0
    except:
        return 0

def _sudo(cmd, password=''):
    if password:
        full = 'sudo -S ' + cmd
        r = subprocess.run(full, shell=True, input=password + '\n', capture_output=True, text=True, timeout=10)
    else:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    return r

def ensure_monitor_chain(password=''):
    try:
        _sudo('iptables -N MONITOR_BLOCK 2>/dev/null', password)
        _sudo('iptables -C INPUT -j MONITOR_BLOCK 2>/dev/null || iptables -I INPUT -j MONITOR_BLOCK', password)
    except:
        pass

def block_ip(ip, password=''):
    try:
        ensure_monitor_chain(password)
        r = _sudo('iptables -A MONITOR_BLOCK -s %s -j DROP' % ip, password)
        if r.returncode == 0:
            return True, 'IP %s bloqueada' % ip
        return False, r.stderr or 'Error al bloquear'
    except Exception as e:
        return False, str(e)

def unblock_ip(ip, password=''):
    try:
        ensure_monitor_chain(password)
        r = _sudo('iptables -D MONITOR_BLOCK -s %s -j DROP' % ip, password)
        if r.returncode == 0:
            return True, 'IP %s desbloqueada' % ip
        return False, r.stderr or 'Error al desbloquear'
    except Exception as e:
        return False, str(e)

def get_blocked_ips(password=''):
    try:
        ensure_monitor_chain(password)
        r = _sudo('iptables -L MONITOR_BLOCK -n', password)
        ips = []
        for line in r.stdout.split('\n'):
            parts = line.strip().split()
            if len(parts) >= 4 and parts[0] == 'DROP' and parts[3] != '0.0.0.0/0':
                ip = parts[3]
                if ip and ip != '0.0.0.0':
                    ips.append(ip)
        return ips
    except:
        return []

def get_suspicious_ips(password=''):
    try:
        from metrics_db import get_auth_failure_summary
        from collections import Counter
        auth_fails = get_auth_failure_summary('24h', 50)
        ips = Counter()
        for f in auth_fails:
            if f.get('ip'):
                ips[f['ip']] += f['attempts']
        logs = get_recent_auth_log(500)
        for l in logs:
            if l['status'] in ('failed', 'invalid_user') and l.get('ip'):
                ips[l['ip']] += 1
        blocked = set(get_blocked_ips(password))
        return [{'ip': ip, 'attempts': cnt, 'blocked': ip in blocked}
                for ip, cnt in ips.most_common(30) if cnt >= 3]
    except:
        return []
