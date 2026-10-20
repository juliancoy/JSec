"""Local motion clips; no network access or automatic deletion."""
import collections, io, json, queue, shutil, subprocess, threading, time
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageChops

class Recorder:
    def __init__(self, root, start_worker=True):
        self.root=Path(root);self.directory=self.root/'recordings'
        self.directory.mkdir(exist_ok=True,mode=0o700)
        self.config={'computer':False,'sd':None}
        try:self.config.update(json.loads((self.root/'recording.json').read_text()))
        except (OSError,ValueError):pass
        self.lock=threading.Lock();self.frames=queue.Queue(5)
        self.status='Off';self.sd_status='Not configured';self.score=0;self.proc=None
        self.previous=None;self.history=collections.deque(maxlen=10);self.hits=0;self.last_sample=0
        if start_worker:threading.Thread(target=self.worker,daemon=True).start()
    def configure(self, computer, sd):
        if type(computer)!=bool or (sd is not None and type(sd)!=bool):raise ValueError('Invalid recording options')
        with self.lock:
            config={'computer':computer,'sd':sd}
            tmp=self.root/'recording.json.tmp';tmp.write_text(json.dumps(config));tmp.replace(self.root/'recording.json')
            self.config=config
    def snapshot(self):
        return {**self.config,'computer_status':self.status,'sd_status':self.sd_status,'motion_percent':round(self.score,1),'clips':sorted([p.name for p in self.directory.glob('*.mp4') if '.partial.' not in p.name],reverse=True)[:100]}
    def offer(self, jpg):
        if not self.config['computer']:return
        now=time.monotonic()
        if now-self.last_sample<.2:return
        self.last_sample=now
        try:self.frames.put_nowait((now,jpg))
        except queue.Full:pass
    def finish(self):
        if self.proc:
            proc=self.proc;self.proc=None
            proc.stdin.close()
            try:code=proc.wait(timeout=15)
            except subprocess.TimeoutExpired:proc.kill();proc.wait();raise RuntimeError('Clip encoder timed out')
            if code:raise RuntimeError('Clip encoder failed')
            self.temp.rename(self.destination)
    def process(self, now, jpg):
        gray=Image.open(io.BytesIO(jpg)).convert('L').resize((160,90))
        score=0
        if self.previous is not None:
            hist=ImageChops.difference(gray,self.previous).histogram();score=sum(hist[26:])*100/(160*90)
        self.previous=gray;self.score=score
        self.hits=self.hits+1 if score>=3 else 0
        motion=self.hits>=2
        if motion:self.last_motion=now
        if not self.proc and motion:
            used=sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file())
            if used>=2*1024**3 or shutil.disk_usage(self.directory).free<1024**3:
                self.status='Storage limit reached — move clips or free space';return
            name=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            self.destination=self.directory/(name+'.mp4');self.temp=self.directory/(name+'.partial.mp4')
            self.proc=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-f','image2pipe','-framerate','5','-vcodec','mjpeg','-i','pipe:0','-an','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart','-y',str(self.temp)],stdin=subprocess.PIPE,stderr=subprocess.DEVNULL)
            self.started=now
            for frame in self.history:self.proc.stdin.write(frame)
        if self.proc:
            self.proc.stdin.write(jpg);self.status='Recording motion'
            if now-self.last_motion>=10 or now-self.started>=60:self.finish()
        else:self.status='Watching for motion'
        self.history.append(jpg)
    def worker(self):
        while True:
            try:
                try:now,jpg=self.frames.get(timeout=1)
                except queue.Empty:
                    if not self.config['computer'] or time.monotonic()-self.last_sample>3:
                        self.finish();self.previous=None;self.history.clear();self.hits=0
                        self.status='Waiting for camera' if self.config['computer'] else 'Off'
                    continue
                if not self.config['computer']:continue
                self.process(now,jpg)
            except Exception as e:
                self.status=str(e)
                if self.proc:self.proc.kill();self.proc.wait();self.proc=None
                self.previous=None;self.history.clear()
