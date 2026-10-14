import os,unittest,tempfile,pathlib,uuid,asyncio
from unittest.mock import patch
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
os.environ.setdefault('SECRET_KEY','revision-two-test-only-secret-longer-than-thirty-two')
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import User,Scenario,PracticeSession
from app.core.security import create_access_token,create_refresh_token
import app.main as main

async def no_opening(*args,**kwargs):pass
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
if __name__=='__main__':unittest.main()
