import socket,time,sys
sys.path.insert(0,'/tmp/eversecu-cameras/scripts')
from okam_p2p_control import OkamP2PClient

def request(req,timeout=4):
 s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(.2)
 s.sendto(bytes.fromhex('f1300000'),('192.168.168.1',32108));end=time.monotonic()+timeout;sent=0;peer=None;out=[]
 while time.monotonic()<end:
  try:
   d,a=s.recvfrom(65535)
   if d[:2] in [b'\xf1\x41',b'\xf1\x42',b'\xf1\x43']:
    s.sendto(d,a);peer=a
   elif d[:2]==b'\xf1\xe0':s.sendto(bytes.fromhex('f1e10000'),a)
   elif d[:2]==b'\xf1\xd0':
    s.sendto(OkamP2PClient._control_ack(d[6:8]),a);out.append(d);print(repr(d[:1600]),flush=True)
   if peer and time.monotonic()-sent>.6:
    s.sendto(bytes.fromhex('f1e00000'),peer);s.sendto(OkamP2PClient._control_frame(req),peer);sent=time.monotonic()
  except TimeoutError:pass
 if peer:s.sendto(bytes.fromhex('f1f00000'),peer)
 s.close();return out
if __name__=='__main__':
 for pwd in ['888888','admin','']:
  print('factory credential test',repr(pwd),flush=True)
  request(f'GET /get_status.cgi?loginuse=admin&loginpas={pwd}&user=admin&pwd={pwd}&'.encode())
