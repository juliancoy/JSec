import socket,time,struct
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(.2);s.sendto(bytes.fromhex('f1300000'),('192.168.168.1',32108));end=time.monotonic()+18;peer=None;stage=0;last=0;seen=set();counts={}
f=open('/tmp/okam-media.bin','wb')
def cmd(path,seq):
 req=f'GET /{path}&loginuse=admin&loginpas=888888&user=admin&pwd=888888&'.encode();inner=b'\xd1\x00'+seq.to_bytes(2,'big')+bytes.fromhex('010a0000')+len(req).to_bytes(4,'little')+req
 s.sendto(b'\xf1\xd0'+len(inner).to_bytes(2,'big')+inner,peer)
while time.monotonic()<end:
 try:
  d,a=s.recvfrom(65535)
  if d[:2] in [b'\xf1\x41',b'\xf1\x42',b'\xf1\x43']:s.sendto(d,a);peer=a
  elif d[:2]==b'\xf1\xe0':s.sendto(bytes.fromhex('f1e10000'),a)
  elif d[:2]==b'\xf1\xd0':
   s.sendto(bytes.fromhex('f1d10006')+d[4:6]+b'\x00\x01'+d[6:8],a)
   key=(d[5],int.from_bytes(d[6:8],'big'))
   if key not in seen:
    seen.add(key);ch=d[5];counts[ch]=counts.get(ch,0)+1
    if ch==0:print('CONTROL',repr(d[8:180]),flush=True)
    else:
     if counts[ch]<5:print('MEDIA',ch,len(d),d[:100].hex(),flush=True)
     f.write(d[8:])
  if peer and time.monotonic()-last>1:
   s.sendto(bytes.fromhex('f1e00000'),peer)
   if stage<2:cmd('get_status.cgi?name=admin',stage)
   elif stage==2:cmd('livestream.cgi?streamid=10&substream=2',stage)
   elif stage==3:cmd('livestream.cgi?streamid=0&substream=0',stage)
   stage+=1;last=time.monotonic()
 except TimeoutError:pass
print('COUNTS',counts)
if peer:s.sendto(bytes.fromhex('f1f00000'),peer)
f.close()
