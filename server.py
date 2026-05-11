import os
import sys
import json
import time
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import metrics_db
import log_parser
import system_monitor
import alerts

API_TOKEN = 'apolo-monitor-2026-token'
HOST = '0.0.0.0'
PORT = 9999
MONITOR_INTERVAL = 300  # 5 minutes
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

_log_lock = threading.Lock()
_last_parse_sizes = {}
_parse_count = 0

def background_monitor():
    global _last_parse_sizes, _parse_count
    while True:
        try:
            metrics_db.init_db()
            count, _last_parse_sizes = log_parser.run_incremental_parse(_last_parse_sizes)
            _parse_count += count
            metrics_db.cleanup_old_data(720)
        except Exception as e:
            pass
        time.sleep(MONITOR_INTERVAL)

def require_token(params):
    token = params.get('token', [''])[0]
    if token != API_TOKEN:
        return False
    return True

class MonitorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _send_html(self, html, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _send_file(self, filepath):
        ext = os.path.splitext(filepath)[1].lower()
        mime_map = {
            '.html': 'text/html; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon'
        }
        mime = mime_map.get(ext, 'application/octet-stream')
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content)
        except:
            self._send_json({'error': 'File not found'}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.end_headers()

    def do_GET(self):
        global _last_parse_sizes, _parse_count
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        params = urllib.parse.parse_qs(parsed.query)

        if path == '/' or path == '/dashboard':
            self._serve_dashboard()
        elif path == '/api/v1/health':
            self._send_json({'status': 'ok', 'time': time.time(),
                           'parsed_events': _parse_count})
        elif path == '/api/v1/stats/summary':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            self._send_json(metrics_db.get_summary())
        elif path == '/api/v1/stats/senders':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            window = params.get('period', ['24h'])[0]
            limit = int(params.get('limit', ['10'])[0])
            self._send_json(metrics_db.get_top_senders(window, limit))
        elif path == '/api/v1/stats/recipients':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            window = params.get('period', ['24h'])[0]
            limit = int(params.get('limit', ['10'])[0])
            self._send_json(metrics_db.get_top_recipients(window, limit))
        elif path == '/api/v1/stats/timeline':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            window = params.get('period', ['24h'])[0]
            interval = int(params.get('interval', ['300'])[0])
            self._send_json(metrics_db.get_timeline(window, interval))
        elif path == '/api/v1/stats/auth':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            window = params.get('period', ['24h'])[0]
            limit = int(params.get('limit', ['50'])[0])
            self._send_json({
                'events': metrics_db.get_auth_events(window, limit),
                'failures': metrics_db.get_auth_failure_summary(window, 10)
            })
        elif path == '/api/v1/stats/bounces':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            window = params.get('period', ['24h'])[0]
            self._send_json(metrics_db.get_bounce_rate(window))
        elif path == '/api/v1/stats/delivery':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            window = params.get('period', ['24h'])[0]
            self._send_json(metrics_db.get_delivery_stats(window))
        elif path == '/api/v1/stats/domains':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            window = params.get('period', ['24h'])[0]
            self._send_json(metrics_db.get_domain_stats(window))
        elif path == '/api/v1/stats/database':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            self._send_json(metrics_db.get_db_stats())
        elif path == '/api/v1/system/resources':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            data = {
                'cpu_percent': system_monitor.get_cpu_percent(),
                'memory': system_monitor.get_memory_info(),
                'swap': system_monitor.get_swap_info(),
                'disk': system_monitor.get_disk_info(),
                'network': system_monitor.get_network_io(),
                'load': system_monitor.get_system_load(),
                'uptime': system_monitor.get_uptime(),
            }
            self._send_json(data)
        elif path == '/api/v1/system/services':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            self._send_json(system_monitor.get_carbonio_services())
        elif path == '/api/v1/system/auth-logs':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            limit = int(params.get('limit', ['20'])[0])
            self._send_json(system_monitor.get_recent_auth_log(limit))
        elif path == '/api/v1/system/queue':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            self._send_json({'count': system_monitor.get_queue_count()})
        elif path == '/api/v1/monitor/parse':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            try:
                count, _last_parse_sizes = log_parser.run_incremental_parse(_last_parse_sizes)
                _parse_count += count
                self._send_json({'status': 'ok', 'parsed': count, 'total': _parse_count})
            except Exception as e:
                self._send_json({'status': 'error', 'message': str(e)}, 500)
        elif path.startswith('/static/'):
            filepath = os.path.join(STATIC_DIR, path[8:])
            if os.path.exists(filepath) and os.path.isfile(filepath):
                self._send_file(filepath)
            else:
                self._send_json({'error': 'File not found'}, 404)
        elif path == '/api/v1/live-feed':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            limit = int(params.get('limit', ['100'])[0])
            buf = log_parser.get_live_buffer(limit)
            if buf:
                self._send_json(buf)
            else:
                self._send_json(metrics_db.get_recent_events(limit))
        elif path == '/api/v1/live-feed/recent':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            limit = int(params.get('limit', ['100'])[0])
            self._send_json(metrics_db.get_recent_events(limit))
        elif path == '/api/v1/alerts':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            limit = int(params.get('limit', ['50'])[0])
            self._send_json(alerts.get_alerts(limit))
        elif path == '/api/v1/accounts/summary':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            limit = int(params.get('limit', ['50'])[0])
            self._send_json(metrics_db.get_accounts_detailed(limit))
        elif path == '/api/v1/accounts/status':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            email = params.get('email', [''])[0]
            if not email:
                self._send_json({'error': 'Email requerido'}, 400)
                return
            ldap_status = metrics_db.get_account_status_from_ldap(email)
            self._send_json({'email': email, 'status': ldap_status})
        elif path == '/api/v1/accounts/disable':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            email = params.get('email', [''])[0]
            if not email:
                self._send_json({'error': 'Email requerido'}, 400)
                return
            try:
                ok, err = metrics_db.disable_account_in_ldap(email)
                if ok:
                    metrics_db.set_account_disabled(email)
                    self._send_json({'status': 'ok', 'message': f'Cuenta {email} desactivada en Carbonio'})
                else:
                    self._send_json({'status': 'error', 'message': f'Error LDAP: {err[:200]}'})
            except Exception as e:
                self._send_json({'status': 'error', 'message': str(e)[:200]})
        elif path == '/api/v1/all' or path == '/api/v1/full':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            self._send_json(self._get_full_status())
        elif path == '/api/v1/security/suspicious-ips':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            pwd = params.get('password', [''])[0]
            self._send_json(system_monitor.get_suspicious_ips(pwd))
        elif path == '/api/v1/security/blocked-ips':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            pwd = params.get('password', [''])[0]
            ips = system_monitor.get_blocked_ips(pwd)
            self._send_json({'ips': ips, 'count': len(ips)})
        elif path == '/api/v1/security/block-ip':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            ip = params.get('ip', [''])[0]
            pwd = params.get('password', [''])[0]
            if not ip:
                self._send_json({'error': 'IP requerida'}, 400)
                return
            ok, msg = system_monitor.block_ip(ip, pwd)
            self._send_json({'status': 'ok' if ok else 'error', 'message': msg})
        elif path == '/api/v1/security/unblock-ip':
            if not require_token(params):
                self._send_json({'error': 'Invalid token'}, 403)
                return
            ip = params.get('ip', [''])[0]
            pwd = params.get('password', [''])[0]
            if not ip:
                self._send_json({'error': 'IP requerida'}, 400)
                return
            ok, msg = system_monitor.unblock_ip(ip, pwd)
            self._send_json({'status': 'ok' if ok else 'error', 'message': msg})
        else:
            self._serve_dashboard()

    def _serve_dashboard(self):
        index_path = os.path.join(STATIC_DIR, 'index.html')
        if os.path.exists(index_path):
            self._send_file(index_path)
        else:
            self._send_html('<h1>Email Monitor</h1><p>Dashboard not found. Run setup first.</p>')

    def _get_full_status(self):
        try:
            return {
                'summary': metrics_db.get_summary(),
                'senders': metrics_db.get_top_senders('24h', 10),
                'recipients': metrics_db.get_top_recipients('24h', 10),
                'timeline': metrics_db.get_timeline('30d', 3600),
                'bounces': metrics_db.get_bounce_rate('24h'),
                'delivery': metrics_db.get_delivery_stats('24h'),
                'domains': metrics_db.get_domain_stats('24h'),
                'auth_failures': metrics_db.get_auth_failure_summary('24h', 10),
                'resources': {
                    'cpu_percent': system_monitor.get_cpu_percent(),
                    'memory': system_monitor.get_memory_info(),
                    'swap': system_monitor.get_swap_info(),
                    'disk': system_monitor.get_disk_info(),
                    'network': system_monitor.get_network_io(),
                    'load': system_monitor.get_system_load(),
                    'uptime': system_monitor.get_uptime()
                },
                'services': system_monitor.get_carbonio_services(),
                'db_stats': metrics_db.get_db_stats(),
                'live_feed': log_parser.get_live_buffer(20),
                'alerts': alerts.get_alerts(20),
                'accounts': metrics_db.get_accounts_detailed(50)
            }
        except Exception as e:
            return {'error': str(e)}

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128

def run_server():
    metrics_db.init_db()
    metrics_db.cleanup_old_data(720)
    for ev in metrics_db.get_recent_events(200):
        log_parser.add_to_live_buffer(ev)
    global _last_parse_sizes
    server = ThreadedHTTPServer((HOST, PORT), MonitorHandler)
    print(f'Apolo Monitor iniciado en http://0.0.0.0:{PORT}')
    print(f'Dashboard: http://localhost:{PORT}/')
    print(f'Token de acceso: {API_TOKEN}')
    print(f'Intervalo de monitoreo: {MONITOR_INTERVAL}s')
    _last_parse_sizes = {}
    for fp in log_parser.LOG_FILES:
        try:
            _last_parse_sizes[fp] = os.path.getsize(fp)
        except:
            _last_parse_sizes[fp] = 0
    t = threading.Thread(target=background_monitor, daemon=True)
    t.start()
    alert_engine = alerts.AlertEngine()
    alert_engine.start()
    live_tail = log_parser.LiveLogTail()
    live_tail.start()
    print('Monitoreo en tiempo real activado (tail -F /var/log/mail.log)')
    print('Motor de alertas activado (spam, auth attacks, bounces)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServidor detenido.')
        server.server_close()

if __name__ == '__main__':
    run_server()
