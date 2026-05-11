import time
import threading
from collections import defaultdict, deque
from metrics_db import get_summary, get_top_senders, get_auth_failure_summary, get_bounce_rate
from system_monitor import get_recent_auth_log
from datetime import datetime as _dt

ALERTS_BUFFER = deque(maxlen=200)
_alerts_lock = threading.Lock()
_alert_rules = {
    'spam_detection': {'enabled': True, 'min_per_hour': 3},
    'auth_burst': {'enabled': True, 'max_per_10min': 10},
    'high_bounce': {'enabled': True, 'max_bounce_rate': 20},
    'ssh_attack': {'enabled': True, 'max_per_10min': 5},
}

def add_alert(alert_type, severity, title, description, details=None):
    with _alerts_lock:
        ALERTS_BUFFER.appendleft({
            'timestamp': time.time(),
            'datetime': _dt.utcfromtimestamp(time.time() - 21600).strftime('%b %d %H:%M:%S'),
            'type': alert_type,
            'severity': severity,
            'title': title,
            'description': description,
            'details': details or {}
        })

def get_alerts(limit=50, min_severity='low'):
    levels = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    min_lvl = levels.get(min_severity, 3)
    with _alerts_lock:
        result = []
        for a in ALERTS_BUFFER:
            if levels.get(a.get('severity', 'low'), 3) <= min_lvl:
                result.append(a)
            if len(result) >= limit:
                break
        return result

def clear_alerts():
    with _alerts_lock:
        ALERTS_BUFFER.clear()

class AlertEngine:
    def __init__(self):
        self._running = False
        self._thread = None
        self._sender_counts = defaultdict(lambda: defaultdict(int))
        self._last_alert_time = {}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _run_loop(self):
        while self._running:
            try:
                self._check_alerts()
            except:
                pass
            time.sleep(30)

    def _check_alerts(self):
        rules = _alert_rules

        if rules.get('spam_detection', {}).get('enabled', True):
            self._check_spam_senders(rules['spam_detection'].get('min_per_hour', 5))

        if rules.get('auth_burst', {}).get('enabled', True):
            self._check_auth_burst(rules['auth_burst'].get('max_per_10min', 20))

        if rules.get('high_bounce', {}).get('enabled', True):
            self._check_bounce_rate(rules['high_bounce'].get('max_bounce_rate', 20))

        if rules.get('ssh_attack', {}).get('enabled', True):
            self._check_ssh_attacks(rules['ssh_attack'].get('max_per_10min', 5))

    def _check_spam_senders(self, min_count):
        try:
            senders = get_top_senders('1h', 20)
            for s in senders:
                if s['count'] >= min_count:
                    key = f'spam:{s["email"]}'
                    now = time.time()
                    if key in self._last_alert_time and now - self._last_alert_time[key] < 3600:
                        continue
                    self._last_alert_time[key] = now
                    add_alert(
                        'spam', 'high',
                        f'Spam potencial: {s["email"]}',
                        f'Ha enviado {s["count"]} correos en la última hora (límite: {min_count - 1})',
                        {'sender': s['email'], 'count': s['count'], 'threshold': min_count}
                    )
        except:
            pass

    def _check_auth_burst(self, max_count):
        try:
            failures = get_auth_failure_summary('2h', 10)
            for f in failures:
                if f['attempts'] >= max_count:
                    key = f'auth:{f["username"]}:{f["ip"]}'
                    now = time.time()
                    if key in self._last_alert_time and now - self._last_alert_time[key] < 600:
                        continue
                    self._last_alert_time[key] = now
                    add_alert(
                        'auth_attack', 'critical',
                        f'Ataque de autenticación: {f["username"]}',
                        f'{f["attempts"]} intentos desde {f["ip"]} en los últimos 30 min',
                        {'username': f['username'], 'ip': f['ip'], 'attempts': f['attempts']}
                    )
        except:
            pass

    def _check_ssh_attacks(self, max_count):
        try:
            logs = get_recent_auth_log(500)
            cutoff = time.time() - 600
            recent = [l for l in logs if l.get('timestamp', 0) > cutoff]
            failures = [l for l in recent if l['status'] in ('failed', 'invalid_user')]
            successes = [l for l in recent if l['status'] == 'success']
            now = time.time()

            if failures:
                from collections import Counter
                ip_counts = Counter(l['ip'] for l in failures if l.get('ip'))
                for ip, cnt in ip_counts.items():
                    if cnt >= max_count:
                        key = 'ssh:%s' % ip
                        if key in self._last_alert_time and now - self._last_alert_time[key] < 600:
                            continue
                        self._last_alert_time[key] = now
                        users = sorted(set(l['user'] for l in failures if l.get('ip') == ip))
                        username_list = ', '.join(users[:5]) if users else '?'
                        add_alert(
                            'auth_attack', 'high',
                            'Intento SSH desde %s' % ip,
                            '%d intentos en ultimos 10 min (usuarios: %s)' % (cnt, username_list),
                            {'ip': ip, 'attempts': cnt, 'users': users[:5]}
                        )

            for s in successes:
                key = 'ssh_ok:%s@%s' % (s['user'], s['ip'])
                if key in self._last_alert_time and now - self._last_alert_time[key] < 3600:
                    continue
                self._last_alert_time[key] = now
                add_alert(
                    'auth', 'low',
                    'Conexion SSH: %s' % s['user'],
                    'Acceso exitoso desde %s' % s['ip'],
                    {'user': s['user'], 'ip': s['ip']}
                )
        except:
            pass

    def _check_bounce_rate(self, max_rate):
        try:
            bounce = get_bounce_rate('1h')
            if bounce['total'] >= 10 and bounce['rate'] >= max_rate:
                now = time.time()
                key = 'bounce_rate'
                if key in self._last_alert_time and now - self._last_alert_time[key] < 3600:
                    return
                self._last_alert_time[key] = now
                add_alert(
                    'bounce', 'medium',
                    'Tasa de rebotes alta',
                    f'{bounce["rate"]}% de rebote en la última hora ({bounce["bounced"]} de {bounce["total"]})',
                    {'rate': bounce['rate'], 'bounced': bounce['bounced'], 'total': bounce['total']}
                )
        except:
            pass
