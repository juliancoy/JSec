#!/usr/bin/env python3
"""On-demand local camera video, listening and talk-back. No cloud calls."""
import audioop, collections, json, queue, re, socket, subprocess, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from protocol import command,OrderedChannel,MediaFrames,talk_packet
from recording import Recorder
ROOT=Path(__file__).parent
HOST='192.168.168.1'
recorder=Recorder(ROOT)
reconnect=threading.Event()
speaker_volume=0
condition=threading.Condition();latest=None;lease_until=time.monotonic()+30
outgoing=queue.Queue(maxsize=25);audio_chunks=collections.deque(maxlen=250);audio_id=0
state={'connected':False,'ready':False,'frames':0,'last_frame':0,'audio_frames':0,'talk_acks':0,'message':'Connecting','prompt_suppression':'pending','storage':'unknown','media_types':{}}

def touch():
    global lease_until
    lease_until=time.monotonic()+20

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
            recorder.offer(jpg)
            with condition:
                latest=jpg;state['frames']+=1;state['last_frame']=time.monotonic();condition.notify_all()

def ensure_wifi():
    r=subprocess.run(['nmcli','-g','GENERAL.CONNECTION','device','show','wlp2s0'],capture_output=True,text=True,timeout=5)
    if r.stdout.strip()!='okam-local':
        state['message']='Reconnecting camera Wi-Fi'
        subprocess.run(['nmcli','--wait','8','connection','up','okam-local'],capture_output=True,timeout=10,check=True)

def camera():
    global latest,audio_id
    while True:
        if time.monotonic()>lease_until and not recorder.config["computer"]:
            state.update(connected=False,ready=False,message='Idle — camera can sleep');time.sleep(.5);continue
        s=None;proc=None;peer=None;log=None;steps=[]
        try:
            reconnect.clear()
            state.update(ready=False,prompt_suppression='pending',message='Connecting')
            recorder.sd_status='Checking camera' if recorder.config['sd'] is not None else 'Not configured'
            ensure_wifi()
            s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4*1024*1024);s.bind(('192.168.168.10',0));s.settimeout(.01)
            s.sendto(bytes.fromhex('f1300000'),(HOST,32108))
            log=open(ROOT/'ffmpeg.log','ab')
            proc=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','warning','-flags','low_delay','-probesize','32768','-analyzeduration','0','-f','h264','-i','pipe:0','-an','-vf','scale=1152:-2','-q:v','5','-f','image2pipe','-vcodec','mjpeg','-flush_packets','1','pipe:1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
            threading.Thread(target=jpeg_reader,args=(proc,),daemon=True).start()
            # Every fresh transport session authenticates and reapplies these settings.
            steps=[('get_status.cgi?name=admin',0x6001),('get_status.cgi?name=admin',0x6001),
                ('trans_cmd_string.cgi?cmd=2106&command=6&cueToneVolume=0',0x60d1),
                (f'camera_control.cgi?param=25&value={speaker_volume}',0x6012),
                ('camera_control.cgi?param=24&value=25',0x6012),
                ('livestream.cgi?streamid=10&substream=2',0x6037),
                ('audiostream.cgi?streamid=7',0x6031),('get_camera_params.cgi?',0x6003)]
            stage=0;last_command=0;stage_start=time.monotonic();start=stage_start;last_alive=0;last_media=start
            channels={i:OrderedChannel() for i in range(4)};parsers={i:MediaFrames() for i in (1,2)};ctrl=bytearray();talkseq=0;nexttalk=0
            while (time.monotonic()<lease_until or recorder.config["computer"]) and not reconnect.is_set():
                now=time.monotonic()
                if not peer and now-start>8:raise TimeoutError('Camera discovery timed out')
                if peer:
                    if now-last_alive>3:s.sendto(bytes.fromhex('f1e00000'),peer);last_alive=now
                    if stage<len(steps):
                        if now-stage_start>10:raise TimeoutError('Camera initialization timed out at step '+str(stage+1))
                        if now-last_command>.6:s.sendto(command(steps[stage][0],stage),peer);last_command=now
                    elif now-last_media>18:raise TimeoutError('Video stopped; reconnecting')
                    if state['ready'] and now>=nexttalk:
                        try:pcm=outgoing.get_nowait()
                        except queue.Empty:pass
                        else:
                            s.sendto(talk_packet(talkseq,audioop.lin2alaw(pcm,2)),peer);talkseq=(talkseq+1)%65536;nexttalk=now+.04
                try:d,a=s.recvfrom(65535)
                except TimeoutError:continue
                if a[0]!=HOST:continue
                if d[:2] in (b'\xf1A',b'\xf1B',b'\xf1C'):
                    s.sendto(d,a);peer=a;state['connected']=True
                elif d[:2]==b'\xf1\xe0':s.sendto(bytes.fromhex('f1e10000'),a)
                elif d[:6]==bytes.fromhex('f1d10006d103'):state['talk_acks']+=1
                elif d[:2]==b'\xf1\xd0' and len(d)>=8:
                    s.sendto(bytes.fromhex('f1d10006')+d[4:6]+b'\x00\x01'+d[6:8],a)
                    channel=d[5]
                    if channel not in channels:continue
                    data=channels[channel].feed(int.from_bytes(d[6:8],'big'),d[8:])
                    if channel==0:
                        ctrl.extend(data)
                        while len(ctrl)>=8:
                            size=int.from_bytes(ctrl[4:7],'little')
                            if size>1024*1024:raise ValueError('Invalid control length')
                            if len(ctrl)<size+8:break
                            code=int.from_bytes(ctrl[2:4],'little');body=bytes(ctrl[8:8+size]).decode('latin1');del ctrl[:8+size]
                            volume=re.search(r'var outvolume=(\d+)',body)
                            if volume:state['speaker_volume']=int(volume[1])
                            if 'var sdtotal=' in body:
                                m=re.search(r'var sdtotal=(\d+)',body);state['storage']='microSD detected' if m and int(m[1])>0 else 'No microSD — recordings unavailable'
                            if stage<len(steps) and code==steps[stage][1]:
                                if not re.search(r'result\s*=\s*0\s*;',body):raise ValueError('Camera rejected initialization step '+str(stage+1))
                                if stage==2:state['prompt_suppression']='command accepted'
                                if stage==1 and recorder.config['sd'] is not None:
                                    enabled=recorder.config['sd']
                                    card=state['storage']=='microSD detected'
                                    if enabled and not card:
                                        recorder.sd_status='Pending — insert microSD, then click Apply'
                                    else:
                                        if enabled:steps.append(('set_recordsch.cgi?time_schedule_enable=0',0x6029))
                                        path='set_alarm.cgi?record='+('1' if enabled else '0')
                                        if enabled:
                                            path+='&motion_armed=1&enable_alarm_audio=0&schedule_enable=1'
                                            for day in ('sun','mon','tue','wed','thu','fri','sat'):
                                                for part in range(3):path+=f'&schedule_{day}_{part}=-1'
                                        steps.append((path,0x600c))
                                        recorder.sd_status='Applying camera recording setting'
                                if steps[stage][1]==0x600c:
                                    recorder.sd_status=('Camera accepted motion recording — clips not yet verified' if recorder.config['sd'] else 'Camera accepted recording disabled')
                                stage+=1;stage_start=now;last_command=0
                                if stage==len(steps):state.update(ready=True,message='Live');print('Session ready: prompts suppressed, video and two-way audio initialized',flush=True)
                    elif channel in parsers:
                        for header,payload in parsers[channel].feed(data):
                            kind=header[4];state['last_media_header']=header.hex();state['last_media_size']=len(payload);key=f'{channel}:{kind}';state['media_types'][key]=state['media_types'].get(key,0)+1
                            if kind in (0,1):
                                last_media=now;proc.stdin.write(payload);proc.stdin.flush()
                            elif kind==12:
                                # CB54W type 12: 640 G.711 A-law samples every 40ms (16kHz).
                                pcm=audioop.alaw2lin(payload,2)
                                with condition:
                                    audio_id+=1;audio_chunks.append((audio_id,pcm));state['audio_frames']+=1;condition.notify_all()
        except Exception as e:
            state.update(connected=False,ready=False,message=str(e));print('Camera:',e,flush=True)
        finally:
            state.update(connected=False,ready=False)
            if s:
                if peer:
                    try:
                        s.sendto(command('audiostream.cgi?streamid=16',len(steps)),peer)
                        s.sendto(command('livestream.cgi?streamid=16&substream=0',len(steps)+1),peer)
                        s.sendto(bytes.fromhex('f1f00000'),peer)
                    except OSError:pass
                s.close()
            if proc:proc.kill();proc.wait()
            if log:log.close()
            while not outgoing.empty():
                try:outgoing.get_nowait()
                except queue.Empty:break
            with condition:latest=None;audio_chunks.clear()
        time.sleep(2)

class Handler(BaseHTTPRequestHandler):
    def valid_host(self):return self.headers.get('Host') in ('127.0.0.1:8765','localhost:8765')
    def send(self,body,ctype='application/json',code=200):
        self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_POST(self):
        global speaker_volume
        if not self.valid_host() or self.headers.get('Origin') not in (None,'http://127.0.0.1:8765','http://localhost:8765'):
            self.send_error(403);return
        if self.path=='/session':touch();self.send(b'{}');return
        if self.path in ('/speaker/mute','/speaker/enable'):
            speaker_volume=0 if self.path.endswith('/mute') else 10
            state['speaker_volume']=None
            touch();reconnect.set();self.send(b'{}');return
        if self.path=='/recording':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=1024:raise ValueError('Invalid request size')
                options=json.loads(self.rfile.read(size))
                previous_sd=recorder.config['sd']
                recorder.configure(options['computer'],options.get('sd'))
                touch()
                if previous_sd!=options.get('sd') or options.get('sd') is True:reconnect.set()
                self.send(json.dumps(recorder.snapshot()).encode())
            except (ValueError,KeyError,TypeError) as e:self.send(str(e).encode(),'text/plain',400)
            return
        if self.path=='/talk':
            size=int(self.headers.get('Content-Length','0'))
            if size!=1280:self.send_error(400,'Expected 640 mono PCM16 samples');return
            data=self.rfile.read(size)
            if not state['ready']:self.send_error(503,'Camera not ready');return
            touch()
            try:outgoing.put_nowait(data)
            except queue.Full:self.send_error(429,'Audio queue full');return
            self.send(b'{}');return
        self.send_error(404)
    def do_GET(self):
        if not self.valid_host():self.send_error(403);return
        if self.path=='/':self.send((ROOT/'index.html').read_bytes(),'text/html; charset=utf-8')
        elif self.path=='/recording':self.send(json.dumps(recorder.snapshot()).encode())
        elif self.path.startswith('/recordings/'):
            name=self.path[len('/recordings/'):]
            if not re.fullmatch(r'\d{8}-\d{6}-\d{6}\.mp4',name):self.send_error(404);return
            path=recorder.directory/name
            if not path.is_file():self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','video/mp4');self.send_header('Content-Length',str(path.stat().st_size));self.send_header('Content-Disposition',f'attachment; filename="{name}"');self.end_headers()
            try:
                with path.open('rb') as clip:
                    while chunk:=clip.read(65536):self.wfile.write(chunk)
            except (BrokenPipeError,ConnectionResetError):pass
        elif self.path=='/status':
            data=dict(state);data.pop('last_frame');data['last_frame_age']=round(time.monotonic()-state['last_frame'],1) if state['last_frame'] else None
            self.send(json.dumps(data).encode())
        elif self.path in ('/stream.mjpg','/snapshot.jpg','/audio.pcm'):
            touch();self.send_response(200);self.send_header('Cache-Control','no-store');self.send_header('Content-Type','application/octet-stream' if self.path=='/audio.pcm' else ('image/jpeg' if self.path=='/snapshot.jpg' else 'multipart/x-mixed-replace; boundary=frame'));self.end_headers()
            previous=None;lastaudio=audio_id
            try:
                while True:
                    with condition:
                        condition.wait(timeout=1);frame=latest;chunks=[(i,p) for i,p in audio_chunks if i>lastaudio]
                    if self.path=='/audio.pcm':
                        for i,p in chunks:self.wfile.write(p);lastaudio=i
                        if chunks:self.wfile.flush()
                    elif frame is not None and frame is not previous:
                        if self.path=='/snapshot.jpg':self.wfile.write(frame);return
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(frame)).encode()+b'\r\n\r\n'+frame+b'\r\n');self.wfile.flush();previous=frame
                    if time.monotonic()>lease_until:return
            except (BrokenPipeError,ConnectionResetError):pass
        else:self.send_error(404)
    def log_message(self,*args):pass

if __name__=='__main__':
    threading.Thread(target=camera,daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
