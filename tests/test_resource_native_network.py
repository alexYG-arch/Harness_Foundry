"""Native verification resource qualification; explicit host/network opt-in."""

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest

from harness_foundry_factory.local_process import CodexSandboxRunner, LocalCommand


@unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "native receiver opt-in required")
class NativeResourceNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.product = self.root / "product"; self.product.mkdir()
        self.scratch = self.root / "scratch"; self.scratch.mkdir()
        self.other = self.root / "other"; self.other.mkdir()
        self.runner = CodexSandboxRunner(os.environ["HFFACTORY_TEST_CODEX_SANDBOX"])
        self.reads = [self.product, sys.prefix, sys.base_prefix, Path(sys._base_executable).parent,
                      *json.loads(os.environ.get("HFFACTORY_TEST_PYTHON_READ_ROOTS", "[]"))]

    def run_code(self, code, network, *, timeout=20, cancellation_reason=None):
        return self.runner.run(LocalCommand.prepare(argv=[sys.executable, "-B", "-c", code],
            cwd=self.product, read_roots=self.reads, write_roots=[self.scratch], timeout_seconds=timeout,
            environment={"TMPDIR": str(self.scratch), "TMP": str(self.scratch), "TEMP": str(self.scratch),
                         "XDG_CACHE_HOME": str(self.scratch), "FOUNDRY_SCRATCH": str(self.scratch)},
            network=network), cancellation_reason=cancellation_reason)

    def test_temp_sqlite_wal_subprocess_and_protected_product(self):
        code = '''import json,os,sqlite3,tempfile,subprocess,sys
from pathlib import Path
scratch=Path(os.environ['FOUNDRY_SCRATCH'])
with tempfile.TemporaryDirectory() as tmp:
 assert Path(tmp).is_relative_to(scratch)
 c=sqlite3.connect(str(Path(tmp)/'data.sqlite3'))
 assert c.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
 c.execute('create table sample(value text)');c.execute("insert into sample values ('ok')");c.commit()
 assert (Path(tmp)/'data.sqlite3-wal').exists();assert (Path(tmp)/'data.sqlite3-shm').exists()
 c.execute("insert into sample values ('rolled back')");c.rollback()
 assert c.execute('select value from sample').fetchall()==[('ok',)];c.close()
 subprocess.run([sys.executable,'-B','-c',"import tempfile,os;from pathlib import Path;p=Path(tempfile.mkstemp()[1]);assert p.is_relative_to(Path(os.environ['TMPDIR']));p.unlink()"],check=True)
try: Path('must-not-write').write_text('wrong')
except PermissionError: pass
else: raise AssertionError('product became writable')
print('TEMP_SQLITE_PROTECTED_PASS')
'''
        result = self.run_code(code, {"mode": "NONE"})
        self.assertEqual(result["status"], "PASS", result)
        self.assertIn("TEMP_SQLITE_PROTECTED_PASS", result["stdout"])
        self.assertFalse((self.product / "must-not-write").exists())

    def test_owned_unix_http_service_ready_request_close_and_network_denials(self):
        socket_directory = self.scratch / ("long-run-" + "x" * 80)
        socket_directory.mkdir()
        socket_path = str(socket_directory / "service.sock")
        forbidden_path = str(self.scratch / "undeclared.sock")
        code = f'''import socket,socketserver,threading,os,http.client,json
from http.server import BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200); self.end_headers(); self.wfile.write(b'OWNED_INSTANCE_READY')
 def log_message(self,*args): pass
class Server(socketserver.UnixStreamServer): pass
# AF_UNIX limits the supplied address length, not the resolved pathname.
# Restore product cwd before business checks; native scope stays absolute.
product_cwd=os.getcwd();os.chdir({str(socket_directory)!r})
try:s=Server('service.sock',Handler)
finally:os.chdir(product_cwd)
t=threading.Thread(target=s.serve_forever);t.start()
try:
 c=http.client.HTTPConnection('owned-local-service');c.sock=socket.socket(socket.AF_UNIX)
 os.chdir({str(socket_directory)!r})
 try:c.sock.connect('service.sock')
 finally:os.chdir(product_cwd)
 c.request('GET','/ready');r=c.getresponse();assert r.status==200;assert r.read()==b'OWNED_INSTANCE_READY';c.close()
finally: s.shutdown();s.server_close();t.join();os.unlink({socket_path!r})
for kind,address in [(socket.AF_UNIX,{forbidden_path!r}),(socket.AF_INET,('127.0.0.1',0))]:
 q=socket.socket(kind)
 try:q.bind(address)
 except PermissionError:pass
 else:raise AssertionError('undeclared endpoint allowed')
 finally:q.close()
print('OWNED_HTTP_CLOSED_OTHER_ENDPOINTS_DENIED')
'''
        result = self.run_code(code, {"mode": "LOCAL_SERVICE", "unix_sockets": [socket_path]})
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["network"], "LOCAL_SERVICE")
        self.assertFalse(Path(socket_path).exists())
        self.assertFalse(Path(forbidden_path).exists())

    def test_timeout_and_authority_cancel_stop_owned_service_process_group(self):
        for stop in ("timeout", "revoked"):
            socket_path = str(self.scratch / (stop + ".sock"))
            ready = self.scratch / (stop + "-ready")
            late = self.scratch / (stop + "-late")
            child = f'''import socket,time,os
from pathlib import Path
os.chdir({str(self.scratch)!r});s=socket.socket(socket.AF_UNIX);s.bind({stop + '.sock'!r});s.listen(1)
Path({str(ready)!r}).write_text('owned');time.sleep(2);Path({str(late)!r}).write_text('leaked')
'''
            code = f'''import subprocess,sys,time
from pathlib import Path
p=subprocess.Popen([sys.executable,'-B','-c',{child!r}])
deadline=time.monotonic()+5
while not Path({str(ready)!r}).exists():
 if time.monotonic()>deadline:raise RuntimeError('service not ready')
 time.sleep(0.01)
time.sleep(30)
'''
            cancellation = (lambda: "BUILD_AUTHORIZATION_REVOKED" if ready.exists() else None) if stop == "revoked" else None
            with self.subTest(stop=stop):
                result = self.run_code(code, {"mode": "LOCAL_SERVICE", "unix_sockets": [socket_path]},
                                       timeout=0.7 if stop == "timeout" else 10, cancellation_reason=cancellation)
                self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT", result)
                self.assertTrue(ready.exists(), result)
                if stop == "revoked":
                    self.assertEqual(result["cancellation_reason"], "BUILD_AUTHORIZATION_REVOKED")
                with socket.socket(socket.AF_UNIX) as client:
                    with self.assertRaises(ConnectionRefusedError):
                        client.connect(socket_path)
                time.sleep(1.8)
                self.assertFalse(late.exists())

    def test_loopback_tcp_http_ipv4_ipv6_multiple_ports_and_network_boundary(self):
        code = '''import errno,http.client,json,os,socket,threading,urllib.error,urllib.request
from http.server import HTTPServer,BaseHTTPRequestHandler
from pathlib import Path
assert os.environ.get('CODEX_NETWORK_PROXY_ACTIVE')=='1'
assert os.environ.get('CODEX_NETWORK_ALLOW_LOCAL_BINDING')=='1'
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(self.server.identity)
 def log_message(self,*args):pass
class IPv6Server(HTTPServer):address_family=socket.AF_INET6
servers=[];threads=[];closed=[]
try:
 # Two independently owned ports verify the documented loopback-wide grant.
 for server_type,host,identity in [(HTTPServer,'127.0.0.1',b'OWNED_V4'),(HTTPServer,'127.0.0.1',b'SECOND_OWNED_PORT'),(IPv6Server,'::1',b'OWNED_V6')]:
  server=server_type((host,0),Handler);server.identity=identity
  servers.append(server);thread=threading.Thread(target=server.serve_forever);thread.start();threads.append(thread)
 for index,host in [(0,'127.0.0.1'),(0,'localhost'),(1,'127.0.0.1'),(2,'::1')]:
  server=servers[index];client=http.client.HTTPConnection(host,server.server_port,timeout=2)
  try:
   client.request('GET','/ready');response=client.getresponse()
   assert response.status==200;assert response.read()==server.identity
  finally:client.close()
 try:Path('tcp-service-must-not-write').write_text('wrong')
 except PermissionError:pass
 else:raise AssertionError('TCP resource made product writable')
finally:
 for server in servers:
  closed.append((server.address_family,server.server_address))
  server.shutdown();server.server_close()
 for thread in threads:thread.join()
for family,address in closed:
 with socket.socket(family) as client:
  client.settimeout(1)
  try:client.connect(address)
  except ConnectionRefusedError:pass
  else:raise AssertionError('owned listener remains after closure')
for family,address in [(socket.AF_INET,('192.0.2.1',12345)),(socket.AF_INET6,('2001:db8::1',12345))]:
 with socket.socket(family) as client:
  client.settimeout(1)
  try:client.connect(address)
  except PermissionError:pass
  else:raise AssertionError('non-loopback direct network allowed')
# Some native proxy versions retain a DNS-port permission exception. Probe
# the reserved TEST-NET address without sending application bytes; this is
# evidence of the permission ceiling, not successful DNS/service acceptance.
# A receiver that denies the historical exception is narrower, not a failure.
with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as client:
 client.setblocking(False)
 dns_permission=client.connect_ex(('192.0.2.1',53))
 assert dns_permission in (0,errno.EINPROGRESS,errno.EWOULDBLOCK,errno.EPERM,errno.EACCES),dns_permission
 print('DNS_PORT_53_PERMISSION',json.dumps({'connect_ex':dns_permission,
       'denied':dns_permission in (errno.EPERM,errno.EACCES)}))
try:urllib.request.urlopen('http://example.invalid/',timeout=2)
except urllib.error.HTTPError as exc:assert exc.code==403,str(exc)
else:raise AssertionError('non-loopback proxy target allowed')
print('LOOPBACK_TCP_IPV4_LOCALHOST_IPV6_CLOSED_REMOTE_DENIED')
'''
        result = self.run_code(code, {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"})
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["network"], "LOCAL_SERVICE")
        self.assertEqual(result["effective_network_policy"]["tcp"], "LOOPBACK")
        self.assertEqual(result["effective_network_policy"]["external_network"],
                         "DENY_EXCEPT_NATIVE_DNS_PORT_53")
        self.assertIn("LOOPBACK_TCP_IPV4_LOCALHOST_IPV6_CLOSED_REMOTE_DENIED", result["stdout"])
        self.assertFalse((self.product / "tcp-service-must-not-write").exists())

    def test_loopback_udp_ipv4_ipv6_roundtrip_and_close(self):
        code = '''import os,socket
assert os.environ.get('CODEX_NETWORK_PROXY_ACTIVE')=='1'
assert os.environ.get('CODEX_NETWORK_ALLOW_LOCAL_BINDING')=='1'
for family,host in [(socket.AF_INET,'127.0.0.1'),(socket.AF_INET6,'::1')]:
 with socket.socket(family,socket.SOCK_DGRAM) as server, socket.socket(family,socket.SOCK_DGRAM) as client:
  server.settimeout(2);client.settimeout(2)
  server.bind((host,0));client.bind((host,0))
  server_address=server.getsockname();client_address=client.getsockname()
  request=b'OWNED_UDP_REQUEST';response=b'OWNED_UDP_RESPONSE'
  assert client.sendto(request,server_address)==len(request)
  received,peer=server.recvfrom(1024)
  assert received==request;assert peer==client_address
  assert server.sendto(response,peer)==len(response)
  received,peer=client.recvfrom(1024)
  assert received==response;assert peer==server_address
 # Rebinding both exact endpoints proves owned UDP sockets released them;
 # a receive timeout alone would not demonstrate that the sockets closed.
 for address in (server_address,client_address):
  with socket.socket(family,socket.SOCK_DGRAM) as closed_endpoint:
   closed_endpoint.bind(address)
print('LOOPBACK_UDP_IPV4_IPV6_ROUNDTRIP_CLOSED')
'''
        result = self.run_code(code, {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"})
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["network"], "LOCAL_SERVICE")
        self.assertEqual(result["effective_network_policy"]["loopback_protocols"], ["TCP", "UDP"])
        self.assertIn("LOOPBACK_UDP_IPV4_IPV6_ROUNDTRIP_CLOSED", result["stdout"])

    def test_none_and_exact_unix_socket_modes_still_deny_loopback_udp(self):
        code = '''import socket
for family,host in [(socket.AF_INET,'127.0.0.1'),(socket.AF_INET6,'::1')]:
 with socket.socket(family,socket.SOCK_DGRAM) as endpoint:
  try:endpoint.bind((host,0))
  except PermissionError:pass
  else:raise AssertionError('UDP loopback was implicitly granted')
print('LOOPBACK_UDP_NOT_IMPLICITLY_GRANTED')
'''
        networks = [{"mode": "NONE"},
                    {"mode": "LOCAL_SERVICE", "unix_sockets": [str(self.scratch / "owned.sock")]}]
        for network in networks:
            with self.subTest(network=network):
                result = self.run_code(code, network)
                self.assertEqual(result["status"], "PASS", result)
                self.assertIn("LOOPBACK_UDP_NOT_IMPLICITLY_GRANTED", result["stdout"])

    def test_loopback_tcp_port_conflict_and_bounded_readiness_do_not_reuse_service(self):
        ready = self.scratch / "delayed-ready.json"
        child = f'''import socket,time,json,os
from pathlib import Path
# Readiness is published only after this instance owns its listener.
time.sleep(float(os.environ['FOUNDRY_STARTUP_DELAY']))
s=socket.socket();s.bind(('127.0.0.1',0));s.listen(1)
ready=Path({str(ready)!r});pending=ready.with_suffix('.pending')
pending.write_text(json.dumps({{'port':s.getsockname()[1],'identity':'new-owned-instance'}}));pending.replace(ready)
time.sleep(10)
'''
        code = f'''import errno,json,os,socket,subprocess,sys,time
from pathlib import Path
with socket.socket() as occupied:
 occupied.bind(('127.0.0.1',0));occupied.listen(1)
 with socket.socket() as conflicting:
  try:conflicting.bind(occupied.getsockname())
  except OSError as exc:assert exc.errno==errno.EADDRINUSE,exc
  else:raise AssertionError('occupied endpoint was mistaken for a new service')
ready=Path({str(ready)!r})
for delay,budget,expected in [(0.15,2,True),(2,0.15,False)]:
 ready.unlink(missing_ok=True)
 child_env={{**os.environ,'FOUNDRY_STARTUP_DELAY':str(delay)}}
 process=subprocess.Popen([sys.executable,'-B','-c',{child!r}],env=child_env)
 found=False;endpoint=None;deadline=time.monotonic()+budget
 try:
  while time.monotonic()<deadline:
   if ready.exists():
    value=json.loads(ready.read_text());assert value['identity']=='new-owned-instance'
    endpoint=('127.0.0.1',value['port'])
    with socket.create_connection(endpoint,timeout=0.2):pass
    found=True;break
   assert process.poll() is None,'service exited before readiness'
   time.sleep(0.01)
  assert found is expected,(delay,budget,found)
 finally:
  process.terminate();process.wait(timeout=2)
 if endpoint:
  with socket.socket() as client:
   try:client.connect(endpoint)
   except ConnectionRefusedError:pass
   else:raise AssertionError('listener leaked after readiness check')
 if not expected:assert not ready.exists(),'timed-out startup was treated as ready'
print('TCP_PORT_CONFLICT_AND_BOUNDED_READINESS_PASS')
'''
        result = self.run_code(code, {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"}, timeout=10)
        self.assertEqual(result["status"], "PASS", result)
        self.assertIn("TCP_PORT_CONFLICT_AND_BOUNDED_READINESS_PASS", result["stdout"])

    def test_loopback_tcp_timeout_and_cancel_close_owned_descendant(self):
        for stop in ("timeout", "revoked"):
            ready = self.scratch / ("tcp-" + stop + "-ready.json")
            late = self.scratch / ("tcp-" + stop + "-late")
            child = f'''import json,socket,time
from pathlib import Path
s=socket.socket();s.bind(('127.0.0.1',0));s.listen(1)
ready=Path({str(ready)!r});pending=ready.with_suffix('.pending')
pending.write_text(json.dumps({{'port':s.getsockname()[1]}}));pending.replace(ready)
time.sleep(3);Path({str(late)!r}).write_text('leaked')
time.sleep(30)
'''
            code = f'''import subprocess,sys,time
from pathlib import Path
subprocess.Popen([sys.executable,'-B','-c',{child!r}])
deadline=time.monotonic()+5
while not Path({str(ready)!r}).exists():
 if time.monotonic()>deadline:raise RuntimeError('TCP service not ready')
 time.sleep(0.01)
time.sleep(30)
'''
            cancellation = (lambda: "BUILD_AUTHORIZATION_REVOKED" if ready.exists() else None) if stop == "revoked" else None
            with self.subTest(stop=stop):
                result = self.run_code(code, {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"},
                                       timeout=1.5 if stop == "timeout" else 10, cancellation_reason=cancellation)
                self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT", result)
                self.assertTrue(ready.exists(), result)
                if stop == "revoked":
                    self.assertEqual(result["cancellation_reason"], "BUILD_AUTHORIZATION_REVOKED")
                endpoint = ("127.0.0.1", json.loads(ready.read_text())["port"])
                with socket.socket() as client:
                    client.settimeout(1)
                    with self.assertRaises(ConnectionRefusedError):
                        client.connect(endpoint)
                time.sleep(3)
                self.assertFalse(late.exists())

    @unittest.skipUnless(os.environ.get("HFFACTORY_TEST_RESOURCE_NETWORK"), "public read-only network opt-in required")
    def test_external_allowlist_denies_other_host_and_direct_ipv4_ipv6(self):
        code = '''import urllib.request,urllib.error,socket,json,os
assert os.environ.get('CODEX_NETWORK_PROXY_ACTIVE')=='1'
with urllib.request.urlopen('https://example.com/',timeout=10) as response:
 assert response.status==200;assert response.read(128)
try:urllib.request.urlopen('https://example.org/',timeout=5)
except urllib.error.URLError as exc:assert '403' in str(exc),str(exc)
else:raise AssertionError('undeclared host allowed')
for family,address in [(socket.AF_INET,('1.1.1.1',443)),(socket.AF_INET6,('::1',443))]:
 s=socket.socket(family);s.settimeout(2)
 try:s.connect(address)
 except PermissionError:pass
 else:raise AssertionError('direct network allowed')
 finally:s.close()
print('REAL_HTTPS_ALLOWED_UNLISTED_AND_DIRECT_DENIED')
'''
        result = self.run_code(code, {"mode": "REMOTE_SERVICE", "allowed_hosts": ["example.com"]}, timeout=30)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["network"], "REMOTE_SERVICE")
        self.assertEqual(result["effective_network_policy"]["guarantee"], "HOST_ALLOWLIST_NOT_PORT_OR_OPERATION")
