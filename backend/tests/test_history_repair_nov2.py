import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import unittest
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.core.security import get_current_user
from app.api.v1.practice import router
from app.models.user import User
from app.models.practice import Scenario, PracticeSession, PracticeMessage

class HistoryRepairTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db=sessionmaker(bind=self.engine)()
        self.user=User(id=str(uuid4()),username='history',email='history@example.com',hashed_password='unused')
        self.scenario=Scenario(id=str(uuid4()),name='Offline scenario',type='sales')
        self.db.add_all([self.user,self.scenario]);self.db.flush()
        self.session=PracticeSession(id=str(uuid4()),scenario_id=self.scenario.id,user_id=self.user.id,status='active',role_config={})
        self.db.add(self.session);self.db.flush()
        self.db.add(PracticeMessage(session_id=self.session.id,role='user',content='persisted offline turn'))
        self.db.commit()
        app=FastAPI();app.include_router(router)
        app.dependency_overrides[get_db]=lambda:self.db
        app.dependency_overrides[get_current_user]=lambda:self.user
        self.client=TestClient(app)
    def tearDown(self):
        self.client.close();self.db.close();self.engine.dispose()
    def test_detail_returns_session_without_ai_evaluation(self):
        response=self.client.get('/practice/sessions/'+str(self.session.id))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['id'],str(self.session.id))
        self.assertEqual(response.json()['message_count'],1)
    def test_transcript_remains_readable_without_provider(self):
        response=self.client.get('/practice/sessions/'+str(self.session.id)+'/messages')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()[0]['content'],'persisted offline turn')
    def test_other_account_cannot_read_transcript(self):
        self.session.user_id=str(uuid4());self.db.commit()
        response=self.client.get('/practice/sessions/'+str(self.session.id)+'/messages')
        self.assertEqual(response.status_code,404)
