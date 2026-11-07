#!/usr/bin/env python3
"""仅本机可访问的 Surver 服务，提供浏览器兼容的回环代理。"""
import argparse
import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / 'private/surver'
RUN = LOCAL / 'run'
BINARY = LOCAL / 'bin/surver'
UNIT = 'vdot-surver.service'
DEFAULT_WAVE = ROOT / 'stage3/logs/p1-before-20261004.vcd'
SMOKE_WAVE = ROOT / 'stage2/waveform/isolation/VDot8-final.vcd'
EXPECTED_BINARY = '5a6028c5d476c5db65d5eafbc490f385daa22d6ba65ffb82772e0590b1ea719e'


def config():
    return json.loads((RUN / 'config.json').read_text())


def base_url(cfg):
    token = (RUN / 'token').read_text().strip()
    return f'http://127.0.0.1:{cfg["port"]}/{token}'


def request(cfg, suffix):
    req = urllib.request.Request(base_url(cfg) + suffix,
        headers={'Origin': 'https://local-test.vscode-cdn.net'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.status, dict(response.headers), response.read()


def start(args):
    wave = (args.wave or (SMOKE_WAVE if args.smoke else DEFAULT_WAVE)).resolve(strict=True)
    if not wave.is_relative_to(ROOT) or wave.suffix.lower() not in ('.vcd', '.fst', '.ghw'):
        raise ValueError('wave must be an existing waveform within the project')
    if not 1024 <= args.port <= 65534:
        raise ValueError('port must be 1024..65534; port+1 is reserved for backend')
    if hashlib.sha256(BINARY.read_bytes()).hexdigest() != EXPECTED_BINARY:
        raise ValueError('Surver binary identity changed')
    # 拒绝重复启动服务或覆盖活动连接配置。
    if subprocess.run(['systemctl', '--user', 'is-active', '--quiet', UNIT]).returncode == 0:
        raise ValueError('service is already active; stop it before switching waves')
    subprocess.run(['systemctl', '--user', 'reset-failed', UNIT],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for port in (args.port, args.port + 1):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
    RUN.mkdir(parents=True, exist_ok=True)
    RUN.chmod(0o700)
    os.umask(0o077)
    cfg = {'wave': str(wave), 'port': args.port, 'backend_port': args.port + 1,
           'bytes': wave.stat().st_size, 'bind': '127.0.0.1', 'unit': UNIT}
    (RUN / 'token').write_text(secrets.token_urlsafe(32) + '\n')
    (RUN / 'config.json').write_text(json.dumps(cfg, indent=2) + '\n')
    (RUN / 'connection.txt').write_text(base_url(cfg) + '\n')
    subprocess.run(['systemd-run', '--user', '--unit=' + UNIT, '--collect',
        '--service-type=exec', '--property=Restart=no', '--property=MemoryHigh=2G',
        '--property=MemoryMax=4G', '--property=MemorySwapMax=2G',
        '--property=TasksMax=128', '--property=UMask=0077',
        '--property=WorkingDirectory=' + str(ROOT),
        '--property=StandardOutput=append:' + str(RUN / 'service.log'),
        '--property=StandardError=append:' + str(RUN / 'service.log'),
        '/usr/bin/python3', str(Path(__file__).resolve()), 'serve'], check=True)
    print('Started local-only service. Connection URL is in private/surver/run/connection.txt')
    print('Wave:', wave)


def serve():
    cfg = config()
    token = (RUN / 'token').read_text().strip()
    os.umask(0o077)
    with (RUN / 'backend.log').open('a', buffering=1) as log:
        backend = subprocess.Popen([str(BINARY), '--bind-address', '127.0.0.1',
            '--port', str(cfg['backend_port']), '--token', token, cfg['wave']],
            stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, 'RAYON_NUM_THREADS': '2'})
        slots = threading.BoundedSemaphore(8)

        class Proxy(http.server.BaseHTTPRequestHandler):
            def version_string(self):
                # Surfer 使用此请求头识别远程协议。
                return 'Surfer'

            def log_message(self, *_args):
                pass  # URL 含访问凭据，请求路径不能写入日志。

            def cors(self):
                # 仅转发携带随机令牌授权的路径，不使用 Cookie 身份验证。
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Expose-Headers',
                    'Server, x-wellen-version, x-surfer-version, Content-Type')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.send_header('Cache-Control', 'no-store')

            def do_OPTIONS(self):
                self.send_response(204)
                self.cors()
                self.end_headers()

            def do_GET(self):
                if self.path != '/' + token and not self.path.startswith('/' + token + '/'):
                    self.send_response(404)
                    self.cors()
                    self.end_headers()
                    return
                if not slots.acquire(blocking=False):
                    self.send_response(503)
                    self.end_headers()
                    return
                connection = http.client.HTTPConnection('127.0.0.1', cfg['backend_port'], timeout=120)
                try:
                    connection.request('GET', self.path)
                    response = connection.getresponse()
                    self.send_response(response.status)
                    for name, value in response.getheaders():
                        if name.lower() in ('content-type', 'content-length',
                                            'x-wellen-version', 'x-surfer-version'):
                            self.send_header(name, value)
                    self.cors()
                    self.end_headers()
                    while chunk := response.read(65536):
                        self.wfile.write(chunk)
                except (ConnectionError, TimeoutError, OSError):
                    self.close_connection = True
                finally:
                    connection.close()
                    slots.release()

        server = http.server.ThreadingHTTPServer(('127.0.0.1', cfg['port']), Proxy)
        server.daemon_threads = True
        def terminate(_signum, _frame):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, terminate)
        def watch():
            result = backend.wait()
            print('Surver backend exited:', result, flush=True)
            os._exit(result or 1)
        threading.Thread(target=watch, daemon=True).start()
        print(f'Browser proxy listening at 127.0.0.1:{cfg["port"]}; backend loopback only', flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            if backend.poll() is None:
                backend.terminate()
                backend.wait(timeout=10)


def status():
    cfg = config()
    _, headers, body = request(cfg, '/get_status')
    data = json.loads(body)
    assert headers.get('Access-Control-Allow-Origin') == '*'
    print(json.dumps(data, indent=2))


def check():
    cfg = config()
    _, _, body = request(cfg, '/get_status')
    state = json.loads(body)
    assert len(state['file_infos']) == 1
    info = state['file_infos'][0]
    assert info['filename'] == cfg['wave'] and info['last_load_ok']
    # Wellen 的缓冲进度可能暂时超过估计的响应体长度。
    # Surver 只有在响应体解析成功后才设置 last_modification_time。
    assert info['last_modification_time'] is not None and not info['reloading'], 'body is still loading'
    results = {}
    for endpoint in ('get_hierarchy', 'get_time_table', 'get_signals/0'):
        code, headers, data = request(cfg, '/0/' + endpoint)
        assert code == 200 and data
        assert 'Surfer' in headers.get('Server', '')
        assert headers.get('Access-Control-Allow-Origin') == '*'
        assert headers.get('x-wellen-version') == state['wellen_version']
        results[endpoint] = len(data)
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{cfg["port"]}/invalid-token/get_status', timeout=5)
    except urllib.error.HTTPError as err:
        assert err.code == 404
    else:
        raise AssertionError('invalid token was accepted')
    print(json.dumps({'status': 'PASS', 'wave': cfg['wave'], 'version': state['surfer_version'],
        'wellen_version': state['wellen_version'], 'transferred_bytes': results,
        'invalid_token': 'rejected', 'browser_CORS': 'PASS'}, indent=2))


def windows_check():
    # URL 和令牌通过标准输入传递，避免出现在命令参数或公开诊断中。
    command = '''$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$url = [Console]::In.ReadLine()
$r = Invoke-WebRequest -UseBasicParsing -Uri ($url + "/get_status") -TimeoutSec 30
$data = $r.Content | ConvertFrom-Json
[PSCustomObject]@{http_status=$r.StatusCode; surfer_version=$data.surfer_version; wellen_version=$data.wellen_version; file_count=$data.file_infos.Count; last_load_ok=$data.file_infos[0].last_load_ok} | ConvertTo-Json
'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
        input=base_url(config()) + '\n', text=True, encoding='utf-8',
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
    if result.returncode:
        # 不回显可能包含凭据 URL 的标准错误输出。
        raise RuntimeError('Windows localhost probe failed; inspect connection/port forwarding without publishing token')
    data = json.loads(result.stdout.lstrip('\ufeff'))
    assert data['http_status'] == 200 and data['file_count'] == 1 and data['last_load_ok']
    print(json.dumps({'Windows_to_WSL': 'PASS', **data}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status', 'check', 'windows-check', 'url', 'serve'))
    parser.add_argument('--wave', type=Path)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--port', type=int, default=8911)
    args = parser.parse_args()
    if args.action == 'start':
        start(args)
    elif args.action == 'stop':
        subprocess.run(['systemctl', '--user', 'stop', UNIT], check=True)
    elif args.action == 'status':
        status()
    elif args.action == 'check':
        check()
    elif args.action == 'windows-check':
        windows_check()
    elif args.action == 'url':
        print(base_url(config()))
    else:
        serve()


if __name__ == '__main__':
    main()
