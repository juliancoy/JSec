#!/usr/bin/env python3
"""Play a local music file once over the camera's AP-mode talk channel."""
import argparse, signal, socket, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'vendor'))
from okam_p2p_talk import TalkSession, encode_audio, ProtocolError
from okam_p2p_control import authenticated_request

class Plain:
    def encrypt(self,data):return data
    def decrypt(self,data):return data

class LocalTalk(TalkSession):
    def __init__(self,host,timeout):
        super().__init__(host,timeout)
        self.cipher=Plain()
        self.last_report=0
    def connect(self):
        self.socket.sendto(bytes.fromhex('f1300000'),(self.host,32108))
        deadline=time.monotonic()+self.timeout
        while time.monotonic()<deadline:
            try:data,peer=self.socket.recvfrom(65535)
            except TimeoutError:continue
            if peer[0]!=self.host:continue
            if data[:2] in (b'\xf1A',b'\xf1B',b'\xf1C'):
                self.peer=peer;self.socket.sendto(data,peer)
                if data[:2]!=b'\xf1A':
                    self._send_plain(bytes.fromhex('f1e00000'));return
        raise ProtocolError('Camera handshake timed out')
    def _handle_packet(self,packet):
        if packet[:2] in (b'\xf1A',b'\xf1B',b'\xf1C'):
            self._send_plain(packet);return None
        if packet[:2]==b'\xf1\xe0':
            self._send_plain(bytes.fromhex('f1e10000'));return None
        result=super()._handle_packet(packet)
        now=time.monotonic()
        if self.talk_ack_packets and now-self.last_report>5:
            print(f'Camera acknowledged {self.talk_ack_packets} audio packets',flush=True)
            self.last_report=now
        return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('file',type=Path)
    p.add_argument('--volume',type=int,default=10,choices=range(1,32))
    args=p.parse_args()
    args.tone=None;args.max_seconds=600
    args.login_user='admin';args.device_user='admin';args.login_pass='888888';args.p2p_password='888888';args.user_id='0'
    audio=encode_audio(args)
    s=LocalTalk('192.168.168.1',8)
    seq=0;unmuted=False;stream=False
    def request(path):
        nonlocal seq
        result=s.request(authenticated_request(path,args),seq);seq+=1
        return result
    def stop(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:
        s.connect()
        request('get_status.cgi?name=admin&')
        request('get_status.cgi?name=admin&')
        request('trans_cmd_string.cgi?cmd=2106&command=6&cueToneVolume=0&')
        unmuted=True
        request(f'camera_control.cgi?param=25&value={args.volume}&')
        request('livestream.cgi?streamid=10&substream=2&')
        request('audiostream.cgi?streamid=7&');stream=True
        print(f'Streaming {args.file.name}: {len(audio)/16000:.1f}s; speaker volume {args.volume}/31',flush=True)
        s.play(audio)
        if not s.talk_ack_packets:raise ProtocolError('No audio acknowledgements received')
        print('Track complete',flush=True)
    finally:
        s.socket.settimeout(.25)
        if unmuted:
            try:request('camera_control.cgi?param=25&value=0&');print('Speaker muted after playback',flush=True)
            except Exception as e:print('Could not restore mute:',e,flush=True)
        if stream:
            try:request('audiostream.cgi?streamid=16&')
            except Exception as e:print('Audio stop:',e,flush=True)
        if s.peer:s._send_plain(bytes.fromhex('f1f00000'))
        s.close()

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:pass
