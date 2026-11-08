import os,unittest,tempfile,pathlib,asyncio,uuid
from unittest.mock import patch
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
os.environ.setdefault('SECRET_KEY','revision-two-test-only-secret-longer-than-thirty-two')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base,get_db
from app.models import User,Scenario,PracticeSession
from app.models.practice import PracticeMessage
from app.core.security import create_access_token,create_refresh_token
from app.api.v1.practice import router

class PracticePermissionsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.engine=create_engine('sqlite:///'+str(pathlib.Path(self.tmp.name)/'test.db'),connect_args={'check_same_thread':False})
  Base.metadata.create_all(self.engine);self.sessions=sessionmaker(bind=self.engine)
  self.uid=str(uuid.uuid4());self.other=str(uuid.uuid4());self.sid=str(uuid.uuid4());self.scid=str(uuid.uuid4())
  with self.sessions() as db:
   db.add_all([User(id=self.uid,email='one@example.com',username='one',hashed_password='unused'),User(id=self.other,email='two@example.com',username='two',hashed_password='unused'),Scenario(id=self.scid,name='Test',type='初次拜访',status='approved')]);db.flush();db.add(PracticeSession(id=self.sid,user_id=self.uid,scenario_id=self.scid,role_config={}));db.commit()
  def database():
   with self.sessions() as db:yield db
  app=FastAPI();app.include_router(router,prefix='/api/v1');app.dependency_overrides[get_db]=database;self.client=TestClient(app)
 def tearDown(self):self.client.close();self.engine.dispose();self.tmp.cleanup()
 def headers(self,uid):return {'Authorization':'Bearer '+create_access_token(uid)}
 def test_list_requires_login(self):self.assertEqual(self.client.get('/api/v1/practice/sessions-list').status_code,401)
 def test_summary_cannot_read_other_users_session(self):self.assertEqual(self.client.get('/api/v1/practice/sessions/'+self.sid+'/summary',headers=self.headers(self.other)).status_code,404)
 def test_create_session_uses_authenticated_owner_not_query_identity(self):
  payload={'scenario_id':self.scid,'role_config':{'position_level':'manager','personality':'rational','decision_style':'analytical','voice':'male-qn-qingse'}}
  res=self.client.post('/api/v1/practice/sessions?user_id='+self.other,json=payload,headers=self.headers(self.uid));self.assertEqual(res.status_code,200,res.text)
  with self.sessions() as db:self.assertEqual(db.get(PracticeSession,res.json()['session_id']).user_id,self.uid)
 def test_ending_practice_is_saved_and_readable_in_a_fresh_session(self):
  response=self.client.post('/api/v1/practice/sessions/'+self.sid+'/end',headers=self.headers(self.uid))
  self.assertEqual(response.status_code,200,response.text)
  with self.sessions() as db:
   record=db.get(PracticeSession,self.sid);self.assertEqual(record.status,'completed');self.assertIsNotNone(record.ended_at)
  response=self.client.get('/api/v1/practice/sessions/'+self.sid,headers=self.headers(self.uid))
  self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['id'],self.sid)
 def test_normal_user_cannot_modify_scenarios(self):
  res=self.client.put('/api/v1/practice/scenarios/'+self.scid,json={'name':'changed'},headers=self.headers(self.uid));self.assertEqual(res.status_code,403)

 def test_history_detail_restores_saved_settings_and_persona(self):
  with self.sessions() as db:
   record=db.get(PracticeSession,self.sid)
   record.role_config={'position_level':'manager','personality':'rational','decision_style':'analytical','voice':'saved-voice','__persona':{'name':'Saved customer'}}
   record.customer_context={'industry':'manufacturing','preparation':{'goal':'renewal'}}
   record.investigation_result={'company':'Saved company'}
   record.user_context={'difficulty':'hard','practice_goals':['discovery']}
   record.current_phase='proposal';db.commit()
  response=self.client.get('/api/v1/practice/sessions/'+self.sid,headers=self.headers(self.uid))
  self.assertEqual(response.status_code,200,response.text);detail=response.json()
  self.assertEqual(detail['user_context']['difficulty'],'hard')
  self.assertEqual(detail['customer_context']['industry'],'manufacturing')
  self.assertEqual(detail['investigation_result']['company'],'Saved company')
  self.assertEqual(detail['current_phase'],'proposal')
  self.assertEqual(detail['persona']['name'],'Saved customer')
  self.assertEqual(detail['scenario']['name'],'Test')
  self.assertNotIn('__persona',detail['role_config'])

 def test_history_messages_are_ordered_owned_and_preserved(self):
  from datetime import datetime,timedelta
  first=str(uuid.uuid4());second=str(uuid.uuid4());time=datetime(2026,1,1)
  with self.sessions() as db:
   db.add_all([PracticeMessage(id=second,session_id=self.sid,role='ai',content='Saved reply',created_at=time+timedelta(seconds=1)),PracticeMessage(id=first,session_id=self.sid,role='user',content='Saved question',created_at=time)]);db.commit()
  url='/api/v1/practice/sessions/'+self.sid+'/messages'
  self.assertEqual(self.client.get(url).status_code,401)
  self.assertEqual(self.client.get(url,headers=self.headers(self.other)).status_code,404)
  response=self.client.get(url,headers=self.headers(self.uid))
  self.assertEqual(response.status_code,200,response.text)
  self.assertEqual([row['id'] for row in response.json()],[first,second])
  self.assertEqual(self.client.get('/api/v1/practice/sessions/'+self.sid,headers=self.headers(self.other)).status_code,404)
  self.client.post('/api/v1/practice/sessions/'+self.sid+'/end',headers=self.headers(self.uid))
  self.assertEqual(len(self.client.get(url,headers=self.headers(self.uid)).json()),2)

if __name__=='__main__':unittest.main()
