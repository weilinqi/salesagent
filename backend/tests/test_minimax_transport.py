import os,unittest,ssl,json
from unittest.mock import patch
os.environ.setdefault('SECRET_KEY','revision-two-test-only-secret-longer-than-thirty-two')
from app.services.llm.minimax import MiniMaxService
import websockets

class TransportTests(unittest.IsolatedAsyncioTestCase):
 async def test_tts_sends_bearer_header_with_current_websocket_library(self):
  observed=[]
  async def server(ws):
   observed.append(ws.request.headers.get('Authorization'))
   await ws.send(json.dumps({'event':'connected_success'}))
   await ws.recv();await ws.send(json.dumps({'event':'task_started'}))
   await ws.recv();await ws.send(json.dumps({'data':{'audio':'010203'}}))
   await ws.send(json.dumps({'event':'task_finished'}))
  async with websockets.serve(server,'127.0.0.1',0) as listener:
   port=listener.sockets[0].getsockname()[1];real=websockets.connect;contexts=[]
   def connect(url,**kwargs):
    contexts.append(kwargs.pop('ssl'));return real('ws://127.0.0.1:'+str(port),**kwargs)
   with patch('websockets.connect',side_effect=connect):
    audio=[part async for part in MiniMaxService(api_key='synthetic-test-key').text_to_speech_stream('test')]
   self.assertEqual(b''.join(audio),b'\x01\x02\x03');self.assertEqual(observed,['Bearer synthetic-test-key'])
   self.assertTrue(contexts[0].check_hostname);self.assertEqual(contexts[0].verify_mode,ssl.CERT_REQUIRED)
if __name__=='__main__':unittest.main()
