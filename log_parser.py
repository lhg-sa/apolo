import re
import time
import os
import threading
from collections import defaultdict, deque
from datetime import datetime

from metrics_db import store_email_event, store_auth_event

MONTHS = {
    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4,
    'May': 5, 'Jun': 6, 'Jul': 7, 'Aug': 8,
    'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
}

LOG_FILES = ['/var/log/mail.log', '/var/log/mail.log.1']
COMPRESSED_LOG_FILES = ['/var/log/mail.log.2.gz', '/var/log/mail.log.3.gz', '/var/log/mail.log.4.gz']

LOG_TIMESTAMP_RE = re.compile(r'^(\w{3})\s+(\d+)\s+(\d{2}):(\d{2}):(\d{2})')
QUEUE_ID_RE = re.compile(r'\b([0-9A-F]{10,14}):\s+')
FROM_RE = re.compile(r'from=<([^>]*)>')
TO_RE = re.compile(r'to=<([^>]*)>')
STATUS_RE = re.compile(r'status=(\w+)')
SIZE_RE = re.compile(r'size=(\d+)')
DELAY_RE = re.compile(r'delay=([\d.]+)')
RELAY_RE = re.compile(r'relay=([^,\s]+)')
CLIENT_IP_RE = re.compile(r'from unknown\[([^\]]+)\]')

AUTH_FAIL_RE = re.compile(r'warning: \S+\[([^\]]+)\]: SASL LOGIN authentication failed.*sasl_username=(\S+)')
AUTH_FAIL2_RE = re.compile(r'warning: \S+\[([^\]]+)\]: SASL (\S+) authentication failed.*sasl_username=(\S+)')
AUTH_SUCCESS_RE = re.compile(r'sasl_method=(\S+).*sasl_username=(\S+)')

def parse_log_timestamp(month_str, day_str, hour_str, min_str, sec_str, base_time=None):
    if base_time is None:
        base_time = time.time()
    base_dt = datetime.fromtimestamp(base_time)
    month = MONTHS.get(month_str, 1)
    day = int(day_str)
    hour = int(hour_str)
    minute = int(min_str)
    second = int(sec_str)
    year = base_dt.year
    if month > base_dt.month and base_dt.month == 12:
        year = base_dt.year - 1
    try:
        dt = datetime(year, month, day, hour, minute, second)
        return dt.timestamp()
    except:
        return None

def is_amavisd_relay(relay):
    if not relay:
        return False
    return '10024' in relay or '127.0.0.1' in relay or 'localhost' in relay

class PostfixLogParser:
    def __init__(self):
        self._pending = {}
        self._last_position = {}
        self._current_year_logs = []

    def _parse_line(self, line, base_time):
        line = line.strip()
        if not line:
            return
        m = LOG_TIMESTAMP_RE.match(line)
        if not m:
            return
        ts = parse_log_timestamp(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), base_time)
        if ts is None:
            return
        rest = line[m.end():].strip()
        if 'postfix/' not in rest and 'carbonio' not in rest.lower():
            self._check_auth_line(ts, line, rest)
            return
        self._check_auth_line(ts, line, rest)
        self._process_postfix_line(ts, rest)

    def _check_auth_line(self, ts, full_line, rest):
        m = AUTH_FAIL_RE.search(rest)
        if m:
            ip = m.group(1)
            user = m.group(2)
            store_auth_event(ts, user, ip, False, 'LOGIN')
            return
        m = AUTH_FAIL2_RE.search(rest)
        if m:
            ip = m.group(1)
            user = m.group(3)
            store_auth_event(ts, user, ip, False, m.group(2))
            return

    def _process_postfix_line(self, ts, rest):
        qm = QUEUE_ID_RE.search(rest)
        if not qm:
            return
        queue_id = qm.group(1)
        line_after_qid = rest[qm.end():]
        component = ''
        comp_m = re.search(r'postfix/(\w+)', rest)
        if comp_m:
            component = comp_m.group(1)
        if component not in ('pickup', 'qmgr', 'smtp', 'smtpd', 'lmtp', 'cleanup', 'pipe', 'bounce', 'defer'):
            return
        if queue_id not in self._pending:
            self._pending[queue_id] = {
                'from_addr': '',
                'recipients': [],
                'size': 0,
                'timestamp': ts,
                'component': component,
                'client_ip': ''
            }
        pend = self._pending[queue_id]
        if component == 'pickup':
            fm = FROM_RE.search(line_after_qid)
            if fm:
                pend['from_addr'] = fm.group(1)
            pend['component'] = 'pickup'
            pend['timestamp'] = ts
        elif component == 'qmgr':
            fm = FROM_RE.search(line_after_qid)
            if fm:
                val = fm.group(1)
                if '@' in val:
                    pend['from_addr'] = val
                elif pend['from_addr'] and not val:
                    pass
                elif val and not pend['from_addr']:
                    pend['from_addr'] = val
            sz = SIZE_RE.search(line_after_qid)
            if sz:
                pend['size'] = int(sz.group(1))
            pend['timestamp'] = ts
        elif component in ('smtp', 'lmtp'):
            to_m = TO_RE.search(line_after_qid)
            if not to_m:
                return
            recipient = to_m.group(1)
            status_m = STATUS_RE.search(line_after_qid)
            if not status_m:
                return
            status = status_m.group(1)
            relay_m = RELAY_RE.search(line_after_qid)
            relay = relay_m.group(1) if relay_m else ''
            delay_m = DELAY_RE.search(line_after_qid)
            delay = float(delay_m.group(1)) if delay_m else 0.0
            if is_amavisd_relay(relay) and component == 'smtp':
                return
            direction = 'inbound' if component == 'lmtp' else 'outbound'
            sender = pend['from_addr'] if pend['from_addr'] else ''
            sz = pend.get('size', 0)
            client_ip = pend.get('client_ip', '')
            store_email_event(ts, queue_id, sender, recipient, direction, status, sz, relay, delay, client_ip)
            event = {
                'timestamp': ts,
                'datetime': datetime.utcfromtimestamp(ts - 21600).strftime('%b %d %H:%M:%S'),
                'queue_id': queue_id,
                'from': sender,
                'to': recipient,
                'size': sz,
                'status': status,
                'direction': direction,
                'delay': delay,
                'relay': relay,
                'client_ip': client_ip
            }
            if hasattr(self, '_store_callback'):
                self._store_callback(event)
            if queue_id in self._pending:
                del self._pending[queue_id]
        elif component == 'smtpd':
            ip_m = CLIENT_IP_RE.search(rest)
            if ip_m:
                pend['client_ip'] = ip_m.group(1)

    def parse_file(self, filepath, base_time=None):
        if base_time is None:
            base_time = time.time()
        if not os.path.exists(filepath):
            return 0
        count = 0
        try:
            with open(filepath, 'r', errors='replace') as f:
                for line in f:
                    self._parse_line(line, base_time)
                    count += 1
        except PermissionError:
            return 0
        return count

    def parse_compressed_file(self, filepath, base_time=None):
        import gzip
        if base_time is None:
            base_time = time.time()
        if not os.path.exists(filepath):
            return 0
        count = 0
        try:
            with gzip.open(filepath, 'rt', errors='replace') as f:
                for line in f:
                    self._parse_line(line, base_time)
                    count += 1
        except:
            return 0
        return count

def run_initial_parse():
    parser = PostfixLogParser()
    now = time.time()
    total = 0
    for fp in LOG_FILES:
        total += parser.parse_file(fp, now)
    for fp in COMPRESSED_LOG_FILES:
        count = parser.parse_compressed_file(fp, now)
        total += count
        if count > 0:
            pass
    return total

def run_fast_initial_parse():
    parser = PostfixLogParser()
    now = time.time()
    total = 0
    for fp in LOG_FILES:
        total += parser.parse_file(fp, now)
    return total

LIVE_BUFFER = deque(maxlen=500)
_live_buffer_lock = threading.Lock()

def add_to_live_buffer(event):
    with _live_buffer_lock:
        LIVE_BUFFER.appendleft(event)

def get_live_buffer(limit=100):
    with _live_buffer_lock:
        return list(LIVE_BUFFER)[:limit]

def clear_live_buffer():
    with _live_buffer_lock:
        LIVE_BUFFER.clear()

class LiveLogTail:
    def __init__(self, logfile='/var/log/mail.log'):
        self.logfile = logfile
        self._running = False
        self._thread = None
        self._parser = PostfixLogParser()
        self._parser._store_callback = self._store_and_broadcast

    def _store_and_broadcast(self, event):
        add_to_live_buffer(event)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._tail_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _tail_loop(self):
        while self._running:
            try:
                if not os.path.exists(self.logfile):
                    time.sleep(5)
                    continue
                with open(self.logfile, 'r', errors='replace') as f:
                    f.seek(0, 2)
                    while self._running:
                        line = f.readline()
                        if not line:
                            time.sleep(0.5)
                            continue
                        self._parser._parse_line(line, time.time())
            except Exception:
                time.sleep(5)

def run_incremental_parse(previous_size=None):
    parser = PostfixLogParser()
    now = time.time()
    total = 0
    for fp in LOG_FILES:
        if not os.path.exists(fp):
            continue
        try:
            current_size = os.path.getsize(fp)
            if previous_size and fp in previous_size:
                if current_size <= previous_size.get(fp, 0):
                    continue
            with open(fp, 'r', errors='replace') as f:
                if fp in previous_size:
                    f.seek(previous_size[fp])
                for line in f:
                    parser._parse_line(line, now)
                    total += 1
        except:
            continue
    sizes = {}
    for fp in LOG_FILES:
        try:
            sizes[fp] = os.path.getsize(fp)
        except:
            sizes[fp] = 0
    return total, sizes
