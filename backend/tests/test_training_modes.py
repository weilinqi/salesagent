import unittest
from unittest.mock import AsyncMock, patch
from app.services.conversation.customer_voice import generate_customer_opening, dialogue_rules, opening
from app.services.sales_suggestions import SuggestionRequest, sales_suggestions

class TrainingModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_mode_preserves_original_rules(self):
        persona={'title':'高二家长','product':'数学网课'}
        self.assertNotIn('专项训练',dialogue_rules(persona))
        self.assertEqual(dialogue_rules(persona),dialogue_rules({**persona,'training_mode':'full'}))
        self.assertIn('想了解',opening(persona))

    async def test_rejection_opening_and_continuing_rules_without_user_rejection(self):
        persona={'title':'高二家长','product':'数学网课','training_mode':'rejection'}
        chat=AsyncMock(return_value='网课我暂时不考虑，先不用介绍了。')
        result=await generate_customer_opening(persona,chat)
        self.assertIn('不考虑',result)
        self.assertIn('直接说一句拒绝',chat.call_args.kwargs['messages'][0]['content'])
        self.assertIn('后续整段',dialogue_rules(persona))
        self.assertIn('不打算考虑',opening(persona))

    async def test_suggestions_use_module_without_fixed_reason(self):
        request=SuggestionRequest(training_mode='rejection',profile={'product':'手机','target':'老人'})
        with patch('app.services.sales_suggestions.ask_json',new=AsyncMock(return_value={'items':[{'title':'了解顾虑','speech':'您主要顾虑哪方面？'}]})) as call:
            result=await sales_suggestions(request)
        self.assertIn('即使用户未提拒绝',call.call_args.args[0])
        self.assertIn('不假定或透露',call.call_args.args[0])
        self.assertEqual(len(result['items']),1)

    def test_invalid_module_rejected(self):
        with self.assertRaises(ValueError): SuggestionRequest(training_mode='unknown',profile={})
