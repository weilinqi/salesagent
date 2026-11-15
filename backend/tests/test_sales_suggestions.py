import unittest
from unittest.mock import AsyncMock, patch
from app.services.sales_material import MaterialRequest
from app.services.sales_suggestions import sales_suggestions

class SuggestionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_limit_and_deduplication(self):
        body = MaterialRequest(profile={'product':'适老手机','target':'老人','needs':'字体清楚'}, background={})
        entries=[{'title':str(i),'speech':f'参考话术{i}'} for i in range(7)]
        entries.insert(1,entries[0])
        entries.insert(0,{'title':'无效','speech':''})
        with patch('app.services.sales_suggestions.ask_json',new=AsyncMock(return_value={'items':entries})) as call:
            result=await sales_suggestions(body)
        self.assertEqual(len(result['items']),5)
        self.assertEqual(len({x['speech'] for x in result['items']}),5)
        self.assertEqual(call.call_args.args[1]['profile']['target'],'老人')
        self.assertTrue(all(set(x)=={'title','speech'} for x in result['items']))

    async def test_empty_model_result_is_retryable(self):
        with patch('app.services.sales_suggestions.ask_json',new=AsyncMock(return_value={'items':[]})):
            with self.assertRaises(ValueError):
                await sales_suggestions(MaterialRequest(profile={},background={}))

    async def test_more_angles_passes_history_and_filters_repeats(self):
        from app.services.sales_suggestions import SuggestionRequest
        body=SuggestionRequest(profile={'product':'手机','target':'老人'},previous=[{'title':'使用','speech':'您平时怎么使用手机？'}])
        with patch('app.services.sales_suggestions.ask_json',new=AsyncMock(return_value={'items':[{'title':'使用','speech':'您平时怎么使用手机？'},{'title':'售后','speech':'您希望在哪里获得使用帮助？'}]})) as call:
            result=await sales_suggestions(body)
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['items'][0]['title'],'售后')
        self.assertEqual(len(call.call_args.args[1]['previous']),1)
