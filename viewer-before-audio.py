#!/usr/bin/env python3
"""Local O-KAM AP-mode viewer. Python standard library + ffmpeg only."""
import json, os, socket, struct, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
HOST='192.168.168.1'
PASSWORD=os.environ.get('OKAM_CAMERA_PASSWORD','888888')
condition=threading.Condition()
latest=None
state={'connected':False,'frames':0,'last_frame':0,'message':'Connecting to camera'}
PAGE=b'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Local camera</title><style>body{margin:0;background:#10151c;color:#eef3fa;font:16px system-ui}header{padding:20px 28px;display:flex;justify-content:space-between;align-items:center}h1{font-size:22px;margin:0}p{color:#a8b8cc}main{max-width:1280px;margin:auto;padding:0 24px}img{display:block;width:100%;min-height:200px;background:#05080d;border-radius:12px}small{color:#8fa2b8}</style><header><h1>Local camera</h1><span id="status">Connecting...</span></header><main><img src="/stream.mjpg" alt="Waiting for camera video"><p>Direct Wi-Fi connection &middot; O-KAM CB54W &middot; Local processing</p><small id="detail"></small></main><script>async function update(){try{let s=await(await fetch('/status')).json();document.querySelector('#status').textContent=s.last_frame_age!==null&&s.last_frame_age<5?'Live':s.message;document.querySelector('#detail').textContent=s.frames+' frames decoded'+(s.last_frame_age===null?'':' | Latest frame '+s.last_frame_age+'s ago')}catch(e){document.querySelector('#status').textContent='Viewer disconnected'}}setInterval(update,1500);update()</script>'''

def command(path,seq):
 req=f'GET /{path}&loginuse=admin&loginpas={PASSWORD}&user=admin&pwd={PASSWORD}&'.encode()
 inner=b'\xd1\x00'+seq.to_bytes(2,'big')+bytes.fromhex('010a0000')+len(req).to_bytes(4,'little')+req
 return b'\xf1\xd0'+len(inner).to_bytes(2,'big')+inner

def jpeg_reader(proc):
 global latest
 buf=bytearray()
 while True:
  chunk=proc.stdout.read1(65536)
  if not chunk:return
  buf.extend(chunk)
  while True:
   a=buf.find(b'\xff\xd8');b=buf.find(b'\xff\xd9',max(a,0))
   if a<0 or b<0:break
   jpg=bytes(buf[a:b+2]);del buf[:b+2]
   with condition:
    latest=jpg;state['frames']+=1;state['last_frame']=time.monotonic();state['message']='Live';condition.notify_all()

def camera():
 while True:
  proc=None;s=None
  try:
   log=open(os.path.join(os.path.dirname(__file__),'ffmpeg.log'),'ab')
   proc=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','warning','-fflags','nobuffer','-flags','low_delay','-probesize','32768','-analyzeduration','0','-f','h264','-i','pipe:0','-an','-vf','scale=1152:-2','-q:v','5','-f','image2pipe','-vcodec','mjpeg','-flush_packets','1','pipe:1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
   threading.Thread(target=jpeg_reader,args=(proc,),daemon=True).start()
   s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4*1024*1024);s.settimeout(.2)
   s.sendto(bytes.fromhex('f1300000'),(HOST,32108))
   peer=None;start=time.monotonic();last=0;stage=0;expected=0;pending={};media=bytearray();lastmedia=start
   while True:
    now=time.monotonic()
    if not peer and now-start>8:raise TimeoutError('Camera discovery timed out')
    if peer and now-last>1:
     s.sendto(bytes.fromhex('f1e00000'),peer)
     if stage<2:s.sendto(command('get_status.cgi?name=admin',stage),peer)
     elif stage==2:s.sendto(command('livestream.cgi?streamid=10&substream=2',stage),peer)
     stage+=1;last=now
    if now-lastmedia>18:raise TimeoutError('No video received; retrying')
    try:d,a=s.recvfrom(65535)
    except TimeoutError:continue
    if a[0]!=HOST:continue
    if d[:2] in [b'\xf1\x41',b'\xf1\x42',b'\xf1\x43']:
     s.sendto(d,a);peer=a;state['connected']=True
    elif d[:2]==b'\xf1\xe0':s.sendto(bytes.fromhex('f1e10000'),a)
    elif d[:2]==b'\xf1\xd0' and len(d)>=8:
     s.sendto(bytes.fromhex('f1d10006')+d[4:6]+b'\x00\x01'+d[6:8],a)
     if d[5]!=1:continue
     lastmedia=now;seq=int.from_bytes(d[6:8],'big')
     if (seq-expected)%65536>32768:continue
     pending[seq]=d[8:]
     while expected in pending:
      media.extend(pending.pop(expected));expected=(expected+1)%65536
     while len(media)>=32:
      if media[:4]!=bytes.fromhex('55aa15a8'):
       pos=media.find(bytes.fromhex('55aa15a8'),1)
       if pos<0:
        del media[:-3];break
       del media[:pos]
       if len(media)<32:break
      size=int.from_bytes(media[16:20],'little')
      if size>4*1024*1024:raise ValueError('Invalid video frame length')
      if len(media)<size+32:break
      payload=bytes(media[32:32+size]);del media[:32+size]
      proc.stdin.write(payload);proc.stdin.flush()
     if len(pending)>2048:raise TimeoutError('Video packet gap; reconnecting')
  except Exception as e:
   state['message']=str(e);state['connected']=False
   print('Camera:',e,flush=True)
  finally:
   if s:
    if peer:
     try:s.sendto(bytes.fromhex('f1f00000'),peer)
     except OSError:pass
    s.close()
   if proc:
    proc.kill();proc.wait();log.close()
  time.sleep(2)

class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path=='/':
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(PAGE)
  elif self.path=='/status':
   data=dict(state);data.pop('last_frame');data['last_frame_age']=round(time.monotonic()-state['last_frame'],1) if state['last_frame'] else None
   self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(json.dumps(data).encode())
  elif self.path in ['/stream.mjpg','/snapshot.jpg']:
   self.send_response(200);self.send_header('Cache-Control','no-store');self.send_header('Content-Type','image/jpeg' if self.path=='/snapshot.jpg' else 'multipart/x-mixed-replace; boundary=frame');self.end_headers()
   previous=None
   try:
    while True:
     with condition:
      condition.wait_for(lambda:latest is not None and latest is not previous,timeout=15);frame=latest
     if frame is None:continue
     if self.path=='/snapshot.jpg':self.wfile.write(frame);return
     self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(frame)).encode()+b'\r\n\r\n'+frame+b'\r\n');self.wfile.flush();previous=frame
   except (BrokenPipeError,ConnectionResetError):pass
  else:self.send_error(404)
 def log_message(self,*args):pass

if __name__=='__main__':
 threading.Thread(target=camera,daemon=True).start()
 print('Viewer: http://127.0.0.1:8765',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
