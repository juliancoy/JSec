"""Framing for the camera's local UDP transport."""
import os
from urllib.parse import urlencode
MAGIC=bytes.fromhex('55aa15a8')

def command(path,seq):
    auth=urlencode({'loginuse':'admin','loginpas':os.environ.get('OKAM_CAMERA_PASSWORD','888888'),'user':'admin','pwd':os.environ.get('OKAM_CAMERA_PASSWORD','888888')})
    req=f'GET /{path}&{auth}&'.encode()
    inner=b'\xd1\x00'+seq.to_bytes(2,'big')+bytes.fromhex('010a0000')+len(req).to_bytes(4,'little')+req
    return b'\xf1\xd0'+len(inner).to_bytes(2,'big')+inner

class OrderedChannel:
    def __init__(self):self.expected=0;self.pending={}
    def feed(self,seq,payload):
        if (seq-self.expected)%65536>32768:return b''
        self.pending[seq]=payload;out=bytearray()
        while self.expected in self.pending:
            out.extend(self.pending.pop(self.expected));self.expected=(self.expected+1)%65536
        if len(self.pending)>1024:raise ValueError('Packet gap; reconnecting')
        return bytes(out)

class MediaFrames:
    def __init__(self):self.buffer=bytearray()
    def feed(self,payload):
        self.buffer.extend(payload);out=[]
        while len(self.buffer)>=32:
            if self.buffer[:4]!=MAGIC:
                i=self.buffer.find(MAGIC,1)
                if i<0:
                    del self.buffer[:-3];break
                del self.buffer[:i]
                if len(self.buffer)<32:break
            size=int.from_bytes(self.buffer[16:20],'little')
            if size>4*1024*1024:raise ValueError('Invalid media length')
            if len(self.buffer)<32+size:break
            out.append((bytes(self.buffer[:32]),bytes(self.buffer[32:32+size])))
            del self.buffer[:32+size]
        return out

def talk_packet(seq,payload):
    header=bytearray.fromhex('55aa15a808010000000000000000000080020000000000000000000700000000')
    header[16:20]=len(payload).to_bytes(4,'little')
    inner=b'\xd1\x03'+(seq%65536).to_bytes(2,'big')+header+payload
    return b'\xf1\xd0'+len(inner).to_bytes(2,'big')+inner
