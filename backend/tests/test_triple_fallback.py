import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import httpx
from app.services.llm.minimax import MiniMaxService
from app.services.llm.minimax_fallback import MiniMaxAPIError

def service(keys=('one','two','three')):
    with patch('app.config.settings',SimpleNamespace(MINIMAX_USE_PROXY=False)):
        return MiniMaxService(api_key=keys[0],fallback_api_key=keys[1],tertiary_api_key=keys[2])

class TripleFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def run_http(self,kind,all_fail=False):
        seen=[]
        def handler(req):
            key=req.headers['authorization'];seen.append(key)
            if key!='Bearer three' or all_fail:
                return httpx.Response(200,json={'base_resp':{'status_code':2067}})
            if kind=='speech':return httpx.Response(200,json={'data':{'audio':'494433'}})
            if kind=='stream':return httpx.Response(200,headers={'content-type':'text/event-stream'},text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
            return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]})
        client=httpx.AsyncClient
        svc=service()
        with patch('app.services.llm.minimax.httpx.AsyncClient',side_effect=lambda **kw:client(transport=httpx.MockTransport(handler),**kw)):
            if all_fail:
                with self.assertRaises(MiniMaxAPIError) as error:
                    await svc.chat([{'role':'user','content':'test'}])
                self.assertTrue(error.exception.backup_attempted)
            elif kind=='speech':self.assertEqual(await svc.text_to_speech('test'),b'ID3')
            elif kind=='stream':self.assertEqual([x async for x in svc.chat_stream([])],['ok'])
            else:self.assertEqual(await svc.chat([]),'ok')
        self.assertEqual(seen,['Bearer one','Bearer two','Bearer three'])
        self.assertEqual(svc.api_key,'one')
    async def test_text_third_key(self):await self.run_http('text')
    async def test_speech_third_key(self):await self.run_http('speech')
    async def test_stream_third_key(self):await self.run_http('stream')
    async def test_exhausted_stops_after_three(self):await self.run_http('text',True)
    async def test_realtime_replays_to_third(self):
        seen=[];inputs=[]
        async def source():yield b'pcm'
        async def once(svc,stream,text_cb,audio_cb,*args):
            seen.append(svc.api_key);inputs.append([x async for x in stream])
            if svc.api_key!='three':raise MiniMaxAPIError(2067)
            await text_cb('ok');return 'ok'
        with patch.object(MiniMaxService,'_realtime_voice_chat_once',once):
            self.assertEqual(await service().realtime_voice_chat(source(),AsyncMock(),AsyncMock()),'ok')
        self.assertEqual(seen,['one','two','three']);self.assertEqual(inputs,[[b'pcm']]*3)
    def test_duplicate_keys_are_not_retried(self):
        svc=service(('one','one','three'));backup=svc._fallback_service()
        self.assertEqual(backup.api_key,'three');self.assertIsNone(backup._fallback_service())
    def test_missing_second_still_uses_third(self):
        self.assertEqual(service(('one',None,'three'))._fallback_service().api_key,'three')
