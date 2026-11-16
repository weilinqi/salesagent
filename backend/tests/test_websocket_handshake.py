import os,unittest,tempfile,pathlib,uuid,asyncio
from unittest.mock import patch,AsyncMock
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
os.environ.setdefault('SECRET_KEY','revision-two-test-only-secret-longer-than-thirty-two')
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import User,Scenario,PracticeSession
from app.models.practice import PracticeMessage
from app.core.security import create_access_token,create_refresh_token
import app.main as main
real_opening = main._init_persona_and_first_message

async def no_opening(*args,**kwargs):pass

def receive_without_spin_guidance(ws):
 while True:
  message=ws.receive_json()
  # SPIN guidance is an unsolicited side-channel update and may arrive while
  # the test is waiting for a response to a control message.
  if message.get('type') not in ('spin_guidance','spin_guidance_status'):
   return message

class HandshakeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.engine=create_engine('sqlite:///'+str(pathlib.Path(self.tmp.name)/'ws.db'),connect_args={'check_same_thread':False});Base.metadata.create_all(self.engine);self.sessions=sessionmaker(bind=self.engine)
  self.uid=str(uuid.uuid4());self.other=str(uuid.uuid4());self.sid=str(uuid.uuid4());scid=str(uuid.uuid4())
  with self.sessions() as db:
   db.add_all([User(id=self.uid,email='a@example.com',username='a',hashed_password='unused'),User(id=self.other,email='b@example.com',username='b',hashed_password='unused'),Scenario(id=scid,name='Test',type='Test',status='approved')]);db.flush();db.add(PracticeSession(id=self.sid,user_id=self.uid,scenario_id=scid,role_config={}));db.commit()
  self.patches=[patch.object(main,'SessionLocal',self.sessions),patch.object(main,'_init_persona_and_first_message',no_opening)]
  for p in self.patches:p.start()
  self.client=TestClient(main.app)
 def tearDown(self):
  self.client.close()
  for p in reversed(self.patches):p.stop()
  main.manager.active_connections.clear();main.manager.connection_sessions.clear();main.manager.session_states.clear();main.session_manager.sessions.clear()
  self.engine.dispose();self.tmp.cleanup()
 def test_anonymous_socket_is_denied(self):
  with self.assertRaises(WebSocketDisconnect):
   with self.client.websocket_connect('/ws/practice/'+self.sid):pass
 def test_other_user_cannot_join(self):
  with self.assertRaises(WebSocketDisconnect):
   with self.client.websocket_connect('/ws/practice/'+self.sid,subprotocols=['salesagent','bearer.'+create_access_token(self.other)]):pass
 def test_refresh_token_cannot_open_socket(self):
  with self.assertRaises(WebSocketDisconnect):
   with self.client.websocket_connect('/ws/practice/'+self.sid,subprotocols=['salesagent','bearer.'+create_refresh_token(self.uid)]):pass
 def test_disabled_user_is_denied(self):
  with self.sessions() as db:db.get(User,self.uid).is_active=False;db.commit()
  with self.assertRaises(WebSocketDisconnect):
   with self.client.websocket_connect('/ws/practice/'+self.sid,subprotocols=['salesagent','bearer.'+create_access_token(self.uid)]):pass
 def test_owner_can_join_without_echoing_secret(self):
  with self.client.websocket_connect('/ws/practice/'+self.sid,subprotocols=['salesagent','bearer.'+create_access_token(self.uid)]) as ws:
   self.assertEqual(ws.accepted_subprotocol,'salesagent');self.assertEqual(ws.receive_json()['type'],'status_update')

 def test_local_development_accepts_loopback_alias_for_configured_frontend_port(self):
  with patch.object(main.settings,'ENVIRONMENT','development'),patch.object(main.settings,'CORS_ORIGINS',['http://localhost:5173']):
   with self.client.websocket_connect('/ws/practice/'+self.sid,headers={'origin':'http://127.0.0.1:5173'},subprotocols=['salesagent','bearer.'+create_access_token(self.uid)]) as ws:
    self.assertEqual(ws.receive_json()['type'],'status_update')

 def test_production_and_unconfigured_origins_remain_rejected(self):
  for environment,origin in [('production','http://127.0.0.1:5173'),('development','http://127.0.0.1:9999'),('development','http://evil.example:5173'),('development','https://127.0.0.1:5173')]:
   with self.subTest(environment=environment,origin=origin),patch.object(main.settings,'ENVIRONMENT',environment),patch.object(main.settings,'CORS_ORIGINS',['http://localhost:5173']):
    with self.assertRaises(WebSocketDisconnect):
     with self.client.websocket_connect('/ws/practice/'+self.sid,headers={'origin':origin},subprotocols=['salesagent','bearer.'+create_access_token(self.uid)]):pass

 def test_loopback_alias_preserves_explicit_ports_and_rejects_malformed_origins(self):
  from app.core.websocket_origin import allowed_websocket_origin
  self.assertTrue(allowed_websocket_origin('http://[::1]:5173',['http://localhost:5173'],'development'))
  self.assertTrue(allowed_websocket_origin('http://127.0.0.1:80',['http://localhost'],'development'))
  for origin in ['http://127.0.0.1:0','http://127.0.0.1:invalid','http://user@127.0.0.1','http://127.0.0.1/path','http://127.0.0.1?query=1','http://127.0.0.1#fragment']:
   self.assertFalse(allowed_websocket_origin(origin,['http://localhost'],'development'),origin)
 def test_expired_connection_can_renew_same_users_access_token(self):
  from datetime import timedelta
  old=create_access_token(self.uid);new=create_access_token(self.uid,timedelta(hours=2))
  expired=False;real=main.get_user_id_from_token
  def resolve(token):return None if expired and token==old else real(token)
  with patch.object(main,'get_user_id_from_token',side_effect=resolve):
   with self.client.websocket_connect('/ws/practice/'+self.sid,subprotocols=['salesagent','bearer.'+old]) as ws:
    ws.receive_json();ws.receive_json();expired=True
    ws.send_json({'type':'auth_refresh','access_token':new})
    ws.send_json({'type':'stop_playback'})
    self.assertEqual(ws.receive_json()['type'],'status_update')
    self.assertEqual(ws.receive_json()['type'],'playback_stopped')
 def test_disabling_account_revokes_established_socket(self):
  with self.client.websocket_connect('/ws/practice/'+self.sid,subprotocols=['salesagent','bearer.'+create_access_token(self.uid)]) as ws:
   ws.receive_json();ws.receive_json()
   with self.sessions() as db:db.get(User,self.uid).is_active=False;db.commit()
   ws.send_json({'type':'stop_playback'})
   with self.assertRaises(WebSocketDisconnect):ws.receive_json()
 def test_socket_cannot_renew_with_another_accounts_token(self):
  with self.client.websocket_connect('/ws/practice/'+self.sid,subprotocols=['salesagent','bearer.'+create_access_token(self.uid)]) as ws:
   ws.receive_json();ws.receive_json()
   ws.send_json({'type':'auth_refresh','access_token':create_access_token(self.other)})
   with self.assertRaises(WebSocketDisconnect):ws.receive_json()
 def test_database_readiness_failure_returns_503(self):
  with patch.object(main,'engine') as engine:
   engine.connect.side_effect=RuntimeError('secret server path')
   res=self.client.get('/ready');self.assertEqual(res.status_code,503);self.assertNotIn('secret server path',res.text)

 def test_cold_reconnect_restores_context_settings_and_skips_opening(self):
  from datetime import datetime,timedelta
  time=datetime(2026,1,1)
  with self.sessions() as db:
   session=db.get(PracticeSession,self.sid);session.current_phase='proposal'
   session.role_config={'voice':'saved-voice','__persona':{'name':'Saved persona'}}
   session.user_context={'difficulty':'hard'}
   db.add_all([PracticeMessage(session_id=self.sid,role='user',content='Saved question',created_at=time),PracticeMessage(session_id=self.sid,role='ai',content='Saved answer',created_at=time+timedelta(seconds=1))]);db.commit()
  with patch.object(main,'_init_persona_and_first_message',new_callable=AsyncMock) as opening:
   for _ in range(2):
    with self.client.websocket_connect('/ws/practice/'+self.sid,subprotocols=['salesagent','bearer.'+create_access_token(self.uid)]) as ws:
     self.assertEqual(ws.receive_json()['type'],'status_update')
     ws.send_json({'type':'stop_playback'})
     self.assertEqual(receive_without_spin_guidance(ws)['type'],'status_update')
     self.assertEqual(receive_without_spin_guidance(ws)['type'],'playback_stopped')
     info=main.session_manager.get_session_info(self.sid)
     self.assertEqual([m['content'] for m in info['context']],['Saved question','Saved answer'])
     self.assertEqual(info['persona']['name'],'Saved persona')
     self.assertEqual(info['current_phase'],'proposal')
     self.assertEqual(info['user_context']['difficulty'],'hard')
   opening.assert_not_awaited()

 def test_generated_persona_and_opening_are_persisted(self):
  from types import SimpleNamespace
  persona={'name':'Persisted persona','title':'Buyer','company':'Example'}
  main.session_manager.create_session(self.sid,'scenario',{})
  with patch.object(main,'generate_persona_for_session',new_callable=AsyncMock,return_value=persona),patch.object(main,'generate_opening_message',new_callable=AsyncMock,return_value='Saved opening'),patch.object(main,'safe_send_message',new_callable=AsyncMock),patch.object(main,'get_minimax_service',return_value=SimpleNamespace(text_to_speech=AsyncMock(return_value=b'audio'))):
   asyncio.run(real_opening(None,self.sid,'Test','scenario',{}))
  with self.sessions() as db:
   self.assertEqual(db.get(PracticeSession,self.sid).role_config['__persona'],persona)
   rows=db.query(PracticeMessage).filter_by(session_id=self.sid).all()
   self.assertEqual(len(rows),1)
   self.assertIn('Saved opening',rows[0].content)

 def test_reconnect_after_interrupted_opening_reuses_persisted_persona(self):
  from types import SimpleNamespace
  persona={'name':'Existing persona','title':'Buyer','company':'Example'}
  with self.sessions() as db:
   db.get(PracticeSession,self.sid).role_config={'__persona':persona};db.commit()
  async def finish_opening(*args):
   await real_opening(*args)
  with patch.object(main,'generate_persona_for_session',new_callable=AsyncMock) as generate,patch.object(main,'generate_opening_message',new_callable=AsyncMock,return_value='Resumed opening'),patch.object(main,'get_minimax_service',return_value=SimpleNamespace(text_to_speech=AsyncMock(return_value=b'audio'))),patch.object(main,'_init_persona_and_first_message',side_effect=finish_opening):
   with self.client.websocket_connect('/ws/practice/'+self.sid,subprotocols=['salesagent','bearer.'+create_access_token(self.uid)]) as ws:
    ws.receive_json();ws.receive_json()
    opening=ws.receive_json()
    self.assertEqual(opening['persona'],persona)
    self.assertIn('Resumed opening',opening['content'])
   generate.assert_not_awaited()
if __name__=='__main__':unittest.main()
