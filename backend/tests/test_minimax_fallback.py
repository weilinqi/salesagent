"""Credential failover at real service boundaries; all upstream traffic is fake."""
import asyncio
import base64
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from app.services.llm.minimax import MiniMaxService

PRIMARY = 'test-primary-not-a-real-key'
BACKUP = 'test-backup-not-a-real-key'

def service(backup=BACKUP):
    with patch('app.config.settings', SimpleNamespace(
        MINIMAX_API_KEY=PRIMARY, MINIMAX_FALLBACK_API_KEY=backup, MINIMAX_USE_PROXY=False,
    )):
        return MiniMaxService()

def sse(*objects):
    return ''.join('data: '+json.dumps(obj)+'\n\n' for obj in objects) + 'data: [DONE]\n\n'

def token(text):
    return {'choices':[{'delta':{'content':text}}]}

def quota(code=2056):
    return {'base_resp':{'status_code':code,'status_msg':'simulated error'},'data':None}

class HttpBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_balance_402_switches_before_stream_output(self):
        for payload in (None, {'error': {'type': 'insufficient_balance_error',
                                        'message': 'Plan usage limit (2067)'}}):
            calls = []
            def respond(request):
                calls.append(request.headers['authorization'])
                if len(calls) == 1:
                    return httpx.Response(402, json=payload)
                return httpx.Response(200, text=sse(token('backup worked')))
            with self.subTest(payload=payload), self.transport(respond):
                result = ''.join([part async for part in service().chat_stream([])])
                self.assertEqual(result, 'backup worked')
                self.assertEqual(calls, ['Bearer '+PRIMARY, 'Bearer '+BACKUP])

    async def test_exhausted_primary_and_backup_are_reported_to_chat(self):
        from app.services.conversation import streaming
        calls, events = [], []
        def respond(request):
            calls.append(request.headers['authorization'])
            if len(calls) == 1:
                return httpx.Response(402, json={'error': {
                    'type': 'insufficient_balance_error', 'message': PRIMARY}})
            return httpx.Response(429, json={'error': {
                'type': 'rate_limit_error', 'message': BACKUP}})
        assembled = {'messages': [], 'emotion': 'neutral', 'voice_modify': {},
                     'breath_tag': '', 'knowledge_refs': []}
        async def send(event):
            events.append(event)
        before = set(asyncio.all_tasks())
        with self.transport(respond), patch.object(streaming, 'parallel_context_assembly',
                new=AsyncMock(return_value=assembled)), patch(
                'app.websocket.manager.session_manager.get_session_info', return_value={}):
            await streaming.stream_pipeline(send, None, 'offline-session', 'hello',
                                            None, None, None, service(), object())
        endings = [e for e in events if e['type'] == 'ai_streaming_end']
        self.assertEqual(len(endings), 1)
        self.assertIn('备用', endings[0]['content'])
        self.assertIn('额度', endings[0]['content'])
        self.assertNotIn(PRIMARY, str(events))
        self.assertNotIn(BACKUP, str(events))
        self.assertEqual(calls, ['Bearer '+PRIMARY, 'Bearer '+BACKUP])
        self.assertFalse([t for t in asyncio.all_tasks() - before if not t.done()])

    def transport(self, responder):
        real_client = httpx.AsyncClient
        return patch('app.services.llm.minimax.httpx.AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(responder), **kw))

    async def test_primary_success_does_not_call_backup(self):
        calls=[]
        def respond(request):
            calls.append(request.headers['authorization'])
            return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]})
        svc=service()
        with self.transport(respond):
            self.assertEqual(await svc.chat([]),'ok')
        self.assertEqual(calls,['Bearer '+PRIMARY])
        self.assertEqual(svc.api_key,PRIMARY)

    async def test_http_quota_switches_once_preserving_request_and_primary(self):
        calls=[]
        def respond(request):
            calls.append((request.headers['authorization'],json.loads(request.content)))
            if len(calls)==1: return httpx.Response(429,json=quota())
            return httpx.Response(200,json={'choices':[{'message':{'content':'backup reply'}}]})
        svc=service()
        with self.transport(respond):
            self.assertEqual(await svc.chat([{'role':'user','content':'hello'}],model='MiniMax-M3'),'backup reply')
        self.assertEqual([c[0] for c in calls],['Bearer '+PRIMARY,'Bearer '+BACKUP])
        self.assertEqual(calls[0][1],calls[1][1])
        self.assertEqual(svc.api_key,PRIMARY)

    async def test_both_exhausted_stop_after_two_sanitized_attempts(self):
        calls=[]
        def respond(request):
            calls.append(request.headers['authorization'])
            return httpx.Response(429,json={'error':{'code':2056,'message':PRIMARY+' '+BACKUP}})
        with self.transport(respond):
            with self.assertRaises(RuntimeError) as raised:
                await service().chat([])
        self.assertEqual(len(calls),2)
        self.assertNotIn(PRIMARY,str(raised.exception))
        self.assertNotIn(BACKUP,str(raised.exception))

    async def test_no_backup_or_duplicate_key_never_retries(self):
        for backup in ('',PRIMARY):
            calls=[]
            def respond(request):
                calls.append(request)
                return httpx.Response(429,json=quota())
            with self.subTest(backup=backup), self.transport(respond):
                with self.assertRaises(Exception): await service(backup).chat([])
            self.assertEqual(len(calls),1)

    async def test_content_policy_error_is_not_retried_even_with_429(self):
        calls=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(429,json=quota(1026))
        with self.transport(respond):
            with self.assertRaises(Exception): await service().chat([])
        self.assertEqual(len(calls),1)

    async def test_sse_http_and_business_errors_switch_before_text(self):
        for failure in ('http','business'):
            calls=[]
            def respond(request):
                calls.append(request.headers['authorization'])
                if len(calls)==1:
                    if failure=='http': return httpx.Response(429,json=quota())
                    return httpx.Response(200,text=sse(quota()))
                return httpx.Response(200,text=sse(token('备用回复')))
            with self.subTest(failure=failure), self.transport(respond):
                result=''.join([part async for part in service().chat_stream([])])
            self.assertEqual(result,'备用回复')
            self.assertEqual(calls,['Bearer '+PRIMARY,'Bearer '+BACKUP])

    async def test_no_replay_after_partial_stream_output(self):
        calls=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(200,text=sse(token('first'),quota()))
        received=[]
        with self.transport(respond):
            with self.assertRaises(RuntimeError):
                async for part in service().chat_stream([]): received.append(part)
        self.assertEqual(received,['first'])
        self.assertEqual(len(calls),1)

    async def test_tool_stream_switches_before_tool_output(self):
        calls=[]
        tool={'index':0,'id':'call_test','type':'function','function':{'name':'lookup','arguments':'{}'}}
        def respond(request):
            calls.append(request)
            return httpx.Response(200,text=sse(quota()) if len(calls)==1 else sse({'choices':[{'delta':{'tool_calls':[tool]}}]}))
        with self.transport(respond):
            received=[part async for part in service().chat_stream_with_tools([],tools=[])]
        self.assertTrue(received)
        self.assertEqual(len(calls),2)

    async def test_tts_http_200_quota_returns_backup_audio(self):
        calls=[]
        def respond(request):
            calls.append(request.headers['authorization'])
            return httpx.Response(200,json=quota() if len(calls)==1 else {'base_resp':{'status_code':0},'data':{'audio':'4944330102'}})
        with self.transport(respond):
            audio=await service().text_to_speech('hello')
        self.assertEqual(audio,b'ID3\x01\x02')
        self.assertEqual(calls,['Bearer '+PRIMARY,'Bearer '+BACKUP])

    async def test_http_asr_quota_uses_backup_with_same_audio(self):
        calls=[]
        def respond(request):
            calls.append(request.headers['authorization'])
            return httpx.Response(200,json=quota(1008) if len(calls)==1 else {'text':'hello'})
        with self.transport(respond):
            text=await service().speech_to_text(b'fake-audio')
        self.assertEqual(text,'hello')
        self.assertEqual(calls,['Bearer '+PRIMARY,'Bearer '+BACKUP])

    async def test_concurrent_requests_keep_primary_separate(self):
        calls=[]
        async def respond(request):
            auth=request.headers['authorization']
            name=json.loads(request.content)['messages'][0]['content']
            calls.append((name,auth))
            await asyncio.sleep(0)
            if name=='fail' and auth=='Bearer '+PRIMARY: return httpx.Response(429,json=quota())
            return httpx.Response(200,json={'choices':[{'message':{'content':name}}]})
        svc=service()
        with self.transport(respond):
            replies=await asyncio.gather(svc.chat([{'role':'user','content':'fail'}]),svc.chat([{'role':'user','content':'ok'}]))
        self.assertEqual(replies,['fail','ok'])
        self.assertEqual([auth for name,auth in calls if name=='ok'],['Bearer '+PRIMARY])
        self.assertEqual(svc.api_key,PRIMARY)


class FakeSocket:
    def __init__(self,events): self.events=iter(events)
    async def __aenter__(self): return self
    async def __aexit__(self,*_): pass
    async def recv(self): return json.dumps(next(self.events))
    async def send(self,_): pass
    async def close(self): pass

class WebSocketBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recorded_audio_asr_uses_backup_on_quota_error(self):
        calls=[]
        def connect(*_,**kwargs):
            calls.append(kwargs['additional_headers']['Authorization'])
            if len(calls)==1: return FakeSocket([{'type':'error','error':{'code':2056}}])
            return FakeSocket([{'type':'session.created'},{'type':'session.updated'},
                               {'type':'response.text.done','text':'需要采购办公设备'},
                               {'type':'response.done'}])
        with patch('app.services.audio.files.convert_audio_to_pcm',new=AsyncMock(return_value=b'pcm')), \
             patch('websockets.connect',side_effect=connect):
            result=await service().speech_to_text_realtime(b'recorded-audio')
        self.assertEqual(result,'需要采购办公设备')
        self.assertEqual(calls,['Bearer '+PRIMARY,'Bearer '+BACKUP])

    async def test_realtime_never_retries_after_visible_audio(self):
        events=[{'type':'session.created'},{'type':'session.updated'},
                {'type':'response.audio.delta','delta':base64.b64encode(b'audio').decode()},
                {'type':'error','error':{'code':2056}}]
        async def source():
            yield b'pcm'
        audio=[]
        async def on_audio(chunk): audio.append(chunk)
        async def on_text(_): pass
        with patch('websockets.connect',return_value=FakeSocket(events)) as connect:
            with self.assertRaises(RuntimeError):
                await service().realtime_voice_chat(source(),on_text,on_audio)
        self.assertEqual(connect.call_count,1)
        self.assertEqual(audio,[b'audio'])

    async def test_replay_buffer_stops_growing_at_limit(self):
        from app.services.llm.minimax_fallback import ReplayableAudio
        async def source():
            yield b'123'; yield b'456'; yield b'789'
        replay=ReplayableAudio(source(),limit=4)
        try:
            self.assertEqual([part async for part in replay.iterate()],[b'123',b'456',b'789'])
            self.assertFalse(replay.can_replay)
            self.assertEqual(replay.buffer,[])
        finally: await replay.close()

    async def test_cancelled_attempt_keeps_next_audio_for_backup_and_cleans_up(self):
        from app.services.llm.minimax_fallback import ReplayableAudio
        started=asyncio.Event(); release=asyncio.Event(); closed=asyncio.Event()
        async def source():
            try:
                started.set()
                await release.wait()
                yield b'pending-pcm'
            finally: closed.set()
        replay=ReplayableAudio(source())
        first=replay.iterate()
        task=asyncio.create_task(first.__anext__())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(closed.is_set())
        release.set()
        try:
            self.assertEqual([part async for part in replay.iterate()],[b'pending-pcm'])
        finally: await replay.close()
        self.assertTrue(closed.is_set())

    async def test_tts_quota_at_start_uses_backup(self):
        calls=[]
        def connect(url,**kwargs):
            calls.append(kwargs['additional_headers']['Authorization'])
            if len(calls)==1: return FakeSocket([{'event':'connected_success'},{'event':'task_failed',**quota()}])
            return FakeSocket([{'event':'connected_success'},{'event':'task_started'},{'data':{'audio':'494433'},'is_final':True}])
        with patch('websockets.connect',side_effect=connect):
            audio=b''.join([part async for part in service().text_to_speech_stream('hello')])
        self.assertEqual(audio,b'ID3')
        self.assertEqual(calls,['Bearer '+PRIMARY,'Bearer '+BACKUP])

    async def test_tts_error_after_audio_is_not_replayed(self):
        def connect(*args,**kwargs):
            return FakeSocket([{'event':'connected_success'},{'event':'task_started'},{'data':{'audio':'494433'}},{'event':'task_failed',**quota()}])
        received=[]
        with patch('websockets.connect',side_effect=connect) as mock:
            with self.assertRaises(RuntimeError):
                async for part in service().text_to_speech_stream('hello'): received.append(part)
        self.assertEqual(received,[b'ID3'])
        self.assertEqual(mock.call_count,1)

    async def test_realtime_replays_input_only_before_output(self):
        connections=[]
        class RealtimeSocket(FakeSocket):
            def __init__(self,fail):
                self.received=[]; self.sent=asyncio.Event(); self.number=0
                events=[{'type':'error','error':{'code':2056}}] if fail else [
                    {'type':'response.text.delta','delta':'hello'},
                    {'type':'response.audio.delta','delta':base64.b64encode(b'audio').decode()},
                    {'type':'response.done'},
                ]
                super().__init__([{'type':'session.created'},{'type':'session.updated'},*events])
            async def send(self,message):
                data=json.loads(message)
                if data['type']=='input_audio_buffer.append': self.received.append(base64.b64decode(data['audio']))
                if data['type']=='response.create': self.sent.set()
            async def recv(self):
                self.number+=1
                if self.number>2: await asyncio.wait_for(self.sent.wait(),2)
                return await super().recv()
        def connect(*_,**kwargs):
            socket=RealtimeSocket(not connections)
            connections.append((kwargs['additional_headers']['Authorization'],socket))
            return socket
        async def source():
            yield b'pcm1'; yield b'pcm2'
        texts=[]; audio=[]
        async def on_text(text): texts.append(text)
        async def on_audio(chunk): audio.append(chunk)
        svc=service()
        with patch('websockets.connect',side_effect=connect):
            result=await svc.realtime_voice_chat(source(),on_text,on_audio)
        self.assertEqual(result,'hello')
        self.assertEqual(texts,['hello']); self.assertEqual(audio,[b'audio'])
        self.assertEqual([key for key,_ in connections],['Bearer '+PRIMARY,'Bearer '+BACKUP])
        self.assertEqual([socket.received for _,socket in connections],[[b'pcm1',b'pcm2'],[b'pcm1',b'pcm2']])
        self.assertEqual(svc.api_key,PRIMARY)


if __name__=='__main__': unittest.main()
