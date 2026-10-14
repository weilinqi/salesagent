import os,pathlib,unittest,asyncio,tempfile,subprocess
from unittest.mock import patch
os.environ.setdefault('SECRET_KEY','test-only-revision-two-key-that-is-long-enough')
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
from app.websocket.manager import ConnectionManager

class Socket:
 def __init__(self):self.closed=False;self.protocol=None
 async def accept(self,subprotocol=None):self.protocol=subprotocol
 async def close(self,**kwargs):self.closed=True

class ConnectionTests(unittest.IsolatedAsyncioTestCase):
 async def test_stale_disconnect_does_not_remove_new_socket(self):
  manager=ConnectionManager();old=Socket();new=Socket()
  await manager.connect(old,'session');await manager.connect(new,'session')
  # Delayed cleanup can happen after replacement.
  manager.connection_sessions[old]='session'
  manager.disconnect(old)
  self.assertIs(manager.active_connections.get('session'),new)
 async def test_bearer_subprotocol_is_not_reflected(self):
  manager=ConnectionManager();ws=Socket()
  ws.scope={'subprotocols':['salesagent','bearer.private-token']}
  await manager.connect(ws,'session')
  self.assertEqual(ws.protocol,'salesagent')

class AudioTests(unittest.IsolatedAsyncioTestCase):
 async def test_conversion_failure_cleans_temporary_files(self):
  from app.services.audio.files import convert_audio_to_pcm
  paths=[]
  def run(args,**kwargs):
   paths.extend([pathlib.Path(args[args.index('-i')+1]),pathlib.Path(args[-1])])
   raise subprocess.TimeoutExpired('ffmpeg',10)
  with patch('subprocess.run',side_effect=run):
   self.assertIsNone(await convert_audio_to_pcm(b'broken','audio/webm'))
  self.assertTrue(paths)
  self.assertTrue(all(not p.exists() for p in paths))
 async def test_conversion_returns_final_pcm_and_cleans_files(self):
  from app.services.audio.files import convert_audio_to_pcm
  paths=[]
  def run(args,**kwargs):
   paths.extend([pathlib.Path(args[args.index('-i')+1]),pathlib.Path(args[-1])]);paths[-1].write_bytes(b'pcm')
   return subprocess.CompletedProcess(args,0)
  with patch('subprocess.run',side_effect=run):
   self.assertEqual(await convert_audio_to_pcm(b'audio','audio/webm'),b'pcm')
  self.assertTrue(all(not p.exists() for p in paths))
 def test_debug_disabled_does_not_create_recording(self):
  from app.services.audio.files import retain_debug_audio
  with tempfile.TemporaryDirectory() as root:
   source=pathlib.Path(root)/'input.wav';source.write_bytes(b'voice');target=pathlib.Path(root)/'recordings'
   self.assertIsNone(retain_debug_audio(source,enabled=False,directory=target,retention_hours=24))
   self.assertFalse(target.exists())
 def test_debug_retention_removes_old_files_and_uses_unique_names(self):
  from app.services.audio.files import retain_debug_audio
  with tempfile.TemporaryDirectory() as root:
   source=pathlib.Path(root)/'input.wav';source.write_bytes(b'voice');target=pathlib.Path(root)/'recordings';target.mkdir()
   old=target/'asr-old.wav';old.write_bytes(b'old');os.utime(old,(1,1))
   one=retain_debug_audio(source,enabled=True,directory=target,retention_hours=24)
   two=retain_debug_audio(source,enabled=True,directory=target,retention_hours=24)
   self.assertFalse(old.exists());self.assertNotEqual(one,two);self.assertEqual(one.read_bytes(),b'voice')

if __name__=='__main__':unittest.main()
