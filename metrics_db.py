import sqlite3
import time
import os
import threading

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monitor.db')
_local = threading.local()

def get_conn():
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS email_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            queue_id TEXT,
            sender TEXT,
            recipient TEXT,
            direction TEXT,
            status TEXT,
            size INTEGER DEFAULT 0,
            relay TEXT,
            delay REAL DEFAULT 0,
            client_ip TEXT
        );
        CREATE TABLE IF NOT EXISTS auth_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            username TEXT,
            ip TEXT,
            success INTEGER DEFAULT 0,
            method TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_email_ts ON email_events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_email_status ON email_events(status);
        CREATE INDEX IF NOT EXISTS idx_email_sender ON email_events(sender);
        CREATE INDEX IF NOT EXISTS idx_email_recipient ON email_events(recipient);
        CREATE TABLE IF NOT EXISTS account_status (
            email TEXT PRIMARY KEY,
            status TEXT DEFAULT 'active',
            updated_at REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_auth_ts ON auth_events(timestamp);
    """)
    conn.commit()

def store_email_event(timestamp, queue_id, sender, recipient, direction, status, size=0, relay='', delay=0.0, client_ip=''):
    conn = get_conn()
    conn.execute(
        "INSERT INTO email_events (timestamp, queue_id, sender, recipient, direction, status, size, relay, delay, client_ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (timestamp, queue_id, sender, recipient, direction, status, size, relay, delay, client_ip)
    )
    conn.commit()

def store_auth_event(timestamp, username, ip, success, method=''):
    conn = get_conn()
    conn.execute(
        "INSERT INTO auth_events (timestamp, username, ip, success, method) VALUES (?, ?, ?, ?, ?)",
        (timestamp, username, ip, 1 if success else 0, method)
    )
    conn.commit()

def get_window_seconds(window):
    now = time.time()
    windows = {
        '5m': 300, '10m': 600, '30m': 1800, '1h': 3600,
        '2h': 7200, '3h': 10800, '6h': 21600,
        '24h': 86400, '1w': 604800, '30d': MAX_RETENTION_SECONDS
    }
    return now - min(windows.get(window, 86400), MAX_RETENTION_SECONDS)

MAX_RETENTION_DAYS = 30
MAX_RETENTION_SECONDS = MAX_RETENTION_DAYS * 86400

def get_summary():
    conn = get_conn()
    now = time.time()
    max_cutoff = now - MAX_RETENTION_SECONDS
    results = {}
    for label, seconds in [('5m', 300), ('1h', 3600), ('24h', 86400), ('1w', 604800), ('30d', MAX_RETENTION_SECONDS)]:
        cutoff = max(now - seconds, max_cutoff)
        row = conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN direction='outbound' THEN 1 ELSE 0 END) as outbound, "
            "SUM(CASE WHEN direction='inbound' THEN 1 ELSE 0 END) as inbound, "
            "SUM(CASE WHEN status='bounced' THEN 1 ELSE 0 END) as bounced, "
            "SUM(CASE WHEN status='deferred' THEN 1 ELSE 0 END) as deferred "
            "FROM email_events WHERE timestamp > ?", (cutoff,)
        ).fetchone()
        results[label] = {
            'total': row['total'] or 0,
            'outbound': row['outbound'] or 0,
            'inbound': row['inbound'] or 0,
            'bounced': row['bounced'] or 0,
            'deferred': row['deferred'] or 0
        }
    auth_fail = conn.execute(
        "SELECT COUNT(*) as cnt FROM auth_events WHERE timestamp > ? AND success=0",
        (now - 86400,)
    ).fetchone()['cnt'] or 0
    results['auth_failures_24h'] = auth_fail
    return results

def get_top_senders(window='24h', limit=10):
    conn = get_conn()
    cutoff = max(get_window_seconds(window), time.time() - MAX_RETENTION_SECONDS)
    rows = conn.execute(
        "SELECT sender, COUNT(*) as count FROM email_events "
        "WHERE timestamp > ? AND sender != '' AND sender IS NOT NULL "
        "GROUP BY sender ORDER BY count DESC LIMIT ?",
        (cutoff, limit)
    ).fetchall()
    return [{'email': r['sender'], 'count': r['count']} for r in rows]

def get_top_recipients(window='24h', limit=10):
    conn = get_conn()
    cutoff = max(get_window_seconds(window), time.time() - MAX_RETENTION_SECONDS)
    rows = conn.execute(
        "SELECT recipient, COUNT(*) as count FROM email_events "
        "WHERE timestamp > ? AND recipient != '' AND recipient IS NOT NULL "
        "GROUP BY recipient ORDER BY count DESC LIMIT ?",
        (cutoff, limit)
    ).fetchall()
    return [{'email': r['recipient'], 'count': r['count']} for r in rows]

def get_timeline(window='24h', interval=300):
    conn = get_conn()
    cutoff = get_window_seconds(window)
    rows = conn.execute(
        "SELECT CAST((CAST(timestamp AS INTEGER) / ?) * ? AS INTEGER) as bucket, "
        "COUNT(*) as total, "
        "SUM(CASE WHEN direction='outbound' THEN 1 ELSE 0 END) as outbound, "
        "SUM(CASE WHEN direction='inbound' THEN 1 ELSE 0 END) as inbound "
        "FROM email_events WHERE timestamp > ? "
        "GROUP BY bucket ORDER BY bucket ASC",
        (interval, interval, cutoff)
    ).fetchall()
    return [{
        'timestamp': r['bucket'],
        'total': r['total'] or 0,
        'outbound': r['outbound'] or 0,
        'inbound': r['inbound'] or 0
    } for r in rows]

def get_auth_events(window='24h', limit=50):
    conn = get_conn()
    cutoff = get_window_seconds(window)
    rows = conn.execute(
        "SELECT timestamp, username, ip, success, method FROM auth_events "
        "WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
        (cutoff, limit)
    ).fetchall()
    return [{
        'timestamp': r['timestamp'],
        'username': r['username'],
        'ip': r['ip'],
        'success': bool(r['success']),
        'method': r['method']
    } for r in rows]

def get_auth_failure_summary(window='24h', limit=10):
    conn = get_conn()
    cutoff = get_window_seconds(window)
    rows = conn.execute(
        "SELECT username, ip, COUNT(*) as attempts FROM auth_events "
        "WHERE timestamp > ? AND success=0 "
        "GROUP BY username, ip ORDER BY attempts DESC LIMIT ?",
        (cutoff, limit)
    ).fetchall()
    return [{
        'username': r['username'],
        'ip': r['ip'],
        'attempts': r['attempts']
    } for r in rows]

def get_bounce_rate(window='24h'):
    conn = get_conn()
    cutoff = max(get_window_seconds(window), time.time() - MAX_RETENTION_SECONDS)
    row = conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN status='bounced' THEN 1 ELSE 0 END) as bounced "
        "FROM email_events WHERE timestamp > ?", (cutoff,)
    ).fetchone()
    total = row['total'] or 0
    bounced = row['bounced'] or 0
    return {
        'total': total,
        'bounced': bounced,
        'rate': round((bounced / total * 100) if total > 0 else 0, 2)
    }

def get_delivery_stats(window='24h'):
    conn = get_conn()
    cutoff = get_window_seconds(window)
    row = conn.execute(
        "SELECT AVG(delay) as avg_delay, MAX(delay) as max_delay, "
        "MIN(CASE WHEN delay > 0 THEN delay ELSE NULL END) as min_delay "
        "FROM email_events WHERE timestamp > ? AND delay > 0", (cutoff,)
    ).fetchone()
    return {
        'avg_delay': round(row['avg_delay'] or 0, 2),
        'max_delay': round(row['max_delay'] or 0, 2),
        'min_delay': round(row['min_delay'] or 0, 2)
    }

def get_domain_stats(window='24h'):
    conn = get_conn()
    cutoff = get_window_seconds(window)
    rows = conn.execute(
        "SELECT SUBSTR(recipient, INSTR(recipient, '@') + 1) as domain, "
        "COUNT(*) as count FROM email_events "
        "WHERE timestamp > ? AND recipient LIKE '%@%' AND direction='outbound' "
        "GROUP BY domain ORDER BY count DESC LIMIT 15",
        (cutoff,)
    ).fetchall()
    return [{'domain': r['domain'], 'count': r['count']} for r in rows]

def get_db_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) as c FROM email_events").fetchone()['c']
    auth_total = conn.execute("SELECT COUNT(*) as c FROM auth_events").fetchone()['c']
    last = conn.execute("SELECT MAX(timestamp) as ts FROM email_events").fetchone()['ts']
    return {
        'total_events': total,
        'total_auth_events': auth_total,
        'last_event_time': last
    }

LDAP_HOST = 'correo.fraijanes.gt'
LDAP_PORT = 389
LDAP_BIND_DN = 'uid=zimbra,cn=admins,cn=zimbra'
LDAP_PASSWORD = 'jLOzCRHK'

def _ldap_search(base, filter_str, attrs=None):
    try:
        import subprocess, json
        cmd = ['/opt/zextras/common/bin/ldapsearch',
               '-H', f'ldap://{LDAP_HOST}:{LDAP_PORT}',
               '-x', '-D', LDAP_BIND_DN, '-w', LDAP_PASSWORD,
               '-b', base, filter_str]
        if attrs:
            cmd += attrs
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout
    except:
        return ''

def get_account_status_from_ldap(email):
    domain = email.split('@')[1] if '@' in email else ''
    domain_parts = domain.split('.')
    dc_parts = ','.join([f'dc={p}' for p in domain_parts])
    base = f'ou=people,{dc_parts}'
    out = _ldap_search(base, f'mail={email}', ['zimbraAccountStatus'])
    for line in out.split('\n'):
        if line.startswith('zimbraAccountStatus:'):
            return line.split(':', 1)[1].strip()
    return 'unknown'

def disable_account_in_ldap(email):
    domain = email.split('@')[1] if '@' in email else ''
    domain_parts = domain.split('.')
    dc_parts = ','.join([f'dc={p}' for p in domain_parts])
    base = f'ou=people,{dc_parts}'
    try:
        import subprocess
        # First find the correct DN
        srch = subprocess.run(
            ['/opt/zextras/common/bin/ldapsearch', '-H', f'ldap://{LDAP_HOST}:{LDAP_PORT}',
             '-x', '-D', LDAP_BIND_DN, '-w', LDAP_PASSWORD,
             '-b', base, f'mail={email}', 'dn'],
            capture_output=True, text=True, timeout=10)
        dn_line = ''
        for line in srch.stdout.split('\n'):
            if line.startswith('dn:'):
                dn_line = line[3:].strip()
                break
        if not dn_line:
            return False, f'Cuenta {email} no encontrada en LDAP'
        cmd = ['/opt/zextras/common/bin/ldapmodify',
               '-H', f'ldap://{LDAP_HOST}:{LDAP_PORT}',
               '-x', '-D', LDAP_BIND_DN, '-w', LDAP_PASSWORD]
        inp = f'dn: {dn_line}\nchangetype: modify\nreplace: zimbraAccountStatus\nzimbraAccountStatus: closed\n-\n'
        r = subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=10)
        return r.returncode == 0, r.stderr
    except Exception as e:
        return False, str(e)

def set_account_disabled(email):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO account_status (email, status, updated_at) VALUES (?, 'disabled', ?)",
        (email, time.time())
    )
    conn.commit()

def get_accounts_with_status(limit=50, window='30d'):
    conn = get_conn()
    cutoff = max(time.time() - {'5m':300,'1h':3600,'24h':86400,'1w':604800,'30d':MAX_RETENTION_SECONDS}.get(window, MAX_RETENTION_SECONDS), time.time() - MAX_RETENTION_SECONDS)
    rows = conn.execute(
        "SELECT sender, COUNT(*) as count FROM email_events "
        "WHERE timestamp > ? AND sender != '' AND sender IS NOT NULL AND sender LIKE '%@%' "
        "GROUP BY sender ORDER BY count DESC LIMIT ?",
        (cutoff, limit)
    ).fetchall()
    result = []
    for r in rows:
        email = r['sender']
        row = conn.execute("SELECT status FROM account_status WHERE email = ?", (email,)).fetchone()
        status = row['status'] if row else 'active'
        result.append({'email': email, 'count': r['count'], 'status': status})
    return result

def get_accounts_detailed(limit=50):
    conn = get_conn()
    now = time.time()
    cutoff_30d = now - MAX_RETENTION_SECONDS
    cutoff_24h = now - 86400
    rows = conn.execute(
        "SELECT sender FROM email_events "
        "WHERE timestamp > ? AND sender != '' AND sender IS NOT NULL AND sender LIKE '%@%' "
        "GROUP BY sender ORDER BY COUNT(DISTINCT recipient || queue_id) DESC LIMIT ?",
        (cutoff_30d, limit)
    ).fetchall()
    senders = [r['sender'] for r in rows]
    if not senders:
        return []
    placeholders = ','.join(['?'] * len(senders))
    rows_30d = conn.execute(
        f"SELECT sender, COUNT(DISTINCT recipient || queue_id) as cnt FROM email_events WHERE sender IN ({placeholders}) AND timestamp > ? GROUP BY sender",
        senders + [cutoff_30d]
    ).fetchall()
    rows_24h = conn.execute(
        f"SELECT sender, COUNT(DISTINCT recipient || queue_id) as cnt FROM email_events WHERE sender IN ({placeholders}) AND timestamp > ? GROUP BY sender",
        senders + [cutoff_24h]
    ).fetchall()
    count_30d = {r['sender']: r['cnt'] for r in rows_30d}
    count_24h = {r['sender']: r['cnt'] for r in rows_24h}
    result = []
    for email in senders:
        ldap_status = get_account_status_from_ldap(email)
        if ldap_status == 'unknown':
            row = conn.execute("SELECT status FROM account_status WHERE email = ?", (email,)).fetchone()
            ldap_status = row['status'] if row else 'active'
        result.append({'email': email, 'count_30d': count_30d.get(email, 0), 'count_24h': count_24h.get(email, 0), 'status': ldap_status})
    return result

def get_recent_events(limit=100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT timestamp, queue_id, sender, recipient, direction, status, size, relay, delay, client_ip "
        "FROM email_events ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    def fmt(ts):
        from datetime import datetime
        return datetime.utcfromtimestamp(ts - 21600).strftime('%b %d %H:%M:%S')
    return [{
        'timestamp': r['timestamp'],
        'datetime': fmt(r['timestamp']),
        'queue_id': r['queue_id'],
        'from': r['sender'] or '',
        'to': r['recipient'] or '',
        'size': r['size'] or 0,
        'status': r['status'] or '',
        'direction': r['direction'] or '',
        'delay': r['delay'] or 0,
        'relay': (r['relay'] or '').split('[')[0],
        'client_ip': r['client_ip'] or ''
    } for r in rows]

def cleanup_old_data(hours=720):
    conn = get_conn()
    cutoff = time.time() - (hours * 3600)
    deleted = conn.execute("DELETE FROM email_events WHERE timestamp < ?", (cutoff,)).rowcount
    conn.execute("DELETE FROM auth_events WHERE timestamp < ?", (cutoff,))
    conn.commit()
    return deleted
