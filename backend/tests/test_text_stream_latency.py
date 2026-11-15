import unittest
from unittest.mock import AsyncMock, patch
from app.services.conversation import streaming

class TextLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_text_arrives_before_generation_and_tts_finish(self):
        events = []
        async def send(event): events.append(event)
        class Model:
            async def chat_stream(self, *args, **kwargs):
                yield '这门数学课'
                self_check = [e for e in events if e['type']=='ai_streaming_update']
                assert self_check and self_check[-1]['content']=='这门数学课'
                yield '适合孩子吗？'
            text_to_speech = AsyncMock(return_value=b'audio')
        assembled = dict(messages=[],emotion='neutral',voice_modify={},breath_tag='',knowledge_refs=[])
        with patch.object(streaming,'parallel_context_assembly',new=AsyncMock(return_value=assembled)), patch.object(streaming,'sentence_to_audio_stream',new=AsyncMock(return_value=b'audio')), patch('app.websocket.manager.session_manager.get_session_info',return_value={}):
            await streaming.stream_pipeline(send,None,'test','介绍课程',None,None,None,Model(),object())
        updates = [e for e in events if e['type']=='ai_streaming_update']
        endings = [e for e in events if e['type']=='ai_streaming_end']
        self.assertEqual(len(endings),1)
        self.assertEqual(endings[0]['content'],'这门数学课适合孩子吗？')
        self.assertTrue(all(e['id']==endings[0]['id'] for e in updates))

    def test_split_reasoning_tags_are_not_displayed(self):
        for text in ('<thi','<think>private','<think>private</thi'):
            self.assertEqual(streaming.visible_stream_text(text),'')
        self.assertEqual(streaming.visible_stream_text('<think>private</think>你好'),'你好')
