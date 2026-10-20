import unittest
from protocol import OrderedChannel,MediaFrames,talk_packet

class ProtocolTests(unittest.TestCase):
    def test_reorder_duplicate_and_wrap(self):
        c=OrderedChannel()
        self.assertEqual(c.feed(1,b'b'),b'')
        self.assertEqual(c.feed(0,b'a'),b'ab')
        self.assertEqual(c.feed(0,b'a'),b'')
        c.expected=65535
        self.assertEqual(c.feed(0,b'd'),b'')
        self.assertEqual(c.feed(65535,b'c'),b'cd')

    def test_fragmented_concatenated_media(self):
        p=MediaFrames();frame=talk_packet(0,b'abc')[8:]
        self.assertEqual(p.feed(b'junk'+frame[:13]),[])
        frames=p.feed(frame[13:]+frame)
        self.assertEqual([body for header,body in frames],[b'abc',b'abc'])

    def test_talk_envelope(self):
        packet=talk_packet(65536,b'a'*640)
        self.assertEqual(packet[4:8],bytes.fromhex('d1030000'))
        self.assertEqual(int.from_bytes(packet[2:4],'big'),len(packet)-4)
        self.assertEqual(int.from_bytes(packet[24:28],'little'),640)

if __name__=='__main__':unittest.main()
