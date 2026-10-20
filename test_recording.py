import io,json,subprocess,tempfile,unittest
from PIL import Image,ImageDraw
from recording import Recorder

def frame(x):
    image=Image.new('RGB',(320,180),'black')
    ImageDraw.Draw(image).rectangle((x,20,x+80,160),fill='white')
    out=io.BytesIO();image.save(out,format='JPEG');return out.getvalue()

class RecordingTests(unittest.TestCase):
    def test_motion_clip_and_quiet_tail(self):
        with tempfile.TemporaryDirectory() as root:
            r=Recorder(root,start_worker=False)
            for n in range(10):r.process(n*.2,frame(0))
            self.assertIsNone(r.proc)
            for n in range(10,20):r.process(n*.2,frame(0 if n%2 else 180))
            self.assertIsNotNone(r.proc)
            for n in range(20,80):r.process(n*.2,frame(0))
            self.assertIsNone(r.proc)
            clips=list(r.directory.glob('*.mp4'));self.assertEqual(len(clips),1)
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(clips[0])]))
            self.assertEqual(probe['streams'][0]['codec_name'],'h264')
            self.assertGreater(float(probe['streams'][0]['duration']),10)
    def test_config_persistence_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as root:
            r=Recorder(root,start_worker=False);r.configure(True,True)
            self.assertEqual(Recorder(root,start_worker=False).config,{'computer':True,'sd':True})
            with self.assertRaises(ValueError):r.configure('yes',True)
            self.assertTrue(r.config['computer'])

if __name__=='__main__':unittest.main()
