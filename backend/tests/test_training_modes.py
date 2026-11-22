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

    async def test_price_objection_opening_and_continuing_rules(self):
        persona={
            'title':'高三家长','product':'数学一对一课程','training_mode':'price_objection',
            'price_brand_a':'学而思','price_brand_b':'新东方','price_brand_c':'高途',
            'price_comparison_aspect':'单课时价格',
            'price_concern':'客户认为学而思单课时价格比新东方贵，担心多出的费用不值得。',
        }
        chat=AsyncMock(return_value='学而思单课时价格比新东方贵，我担心多出的费用不值得。')
        result=await generate_customer_opening(persona,chat)
        self.assertIn('学而思',result)
        prompt=chat.call_args.kwargs['messages'][0]['content']
        self.assertIn('第一句必须直接',prompt)
        self.assertIn('不要问候',prompt)
        self.assertIn('price_comparison_aspect',prompt)
        self.assertIn('价格顾虑是主线',dialogue_rules(persona))
        self.assertIn('不必每一轮',dialogue_rules(persona))
        self.assertIn('不自动降价',dialogue_rules(persona))
        self.assertIn('学而思单课时价格比新东方贵',opening(persona))

    def test_price_mode_requires_brands_aspect_and_specific_concern(self):
        from app.services.preparation import PreparationProfile
        profile=PreparationProfile(product='数学一对一课程',target='高三家长',goal='处理价格顾虑')
        self.assertFalse(profile.price_ready)
        ready=PreparationProfile(product='数学一对一课程',target='高三家长',goal='处理价格顾虑',
                                 price_brand_a='学而思',price_brand_b='新东方',
                                 price_comparison_aspect='单课时价格',
                                 price_concern='客户认为学而思单课时价格比新东方贵，担心不值得。')
        self.assertTrue(ready.price_ready)
        short_concern=PreparationProfile(product='数学一对一课程',target='高三家长',goal='处理价格顾虑',
                                         price_brand_a='学而思',price_brand_b='新东方',
                                         price_comparison_aspect='单课时价格',
                                         price_concern='学而思价格更贵')
        self.assertTrue(short_concern.price_ready)

    async def test_price_objection_suggestions_focus_on_value_and_comparison(self):
        request=SuggestionRequest(training_mode='price_objection',profile={'product':'数学一对一课程','target':'高三家长'})
        with patch('app.services.sales_suggestions.ask_json',new=AsyncMock(return_value={'items':[{'title':'问清比较对象','speech':'您主要是和预算比，还是和别的课程比？'}]})) as call:
            result=await sales_suggestions(request)
        self.assertIn('价格异议处理',call.call_args.args[0])
        self.assertIn('不要直接建议打折',call.call_args.args[0])
        self.assertEqual(len(result['items']),1)

    def test_price_objection_guidance_uses_price_specific_prompts_and_defaults(self):
        from app.services.conversation.spin_guidance import _coach_prompt, _normalize
        prompt = _coach_prompt({'transcript':'客户：价格有点高。','phase':'problem','round_number':1,'training_mode':'price_objection'})
        system_prompt = prompt[0]['content']
        self.assertIn('价格异议处理专项',system_prompt)
        self.assertIn('不要求客户每一轮',system_prompt)
        self.assertIn('不得直接建议降价',system_prompt)
        guidance = _normalize({}, 'price_objection')
        self.assertIn('和什么相比',guidance['focus'])
        self.assertIn('不要直接降价',guidance['reminder'])

    def test_invalid_module_rejected(self):
        with self.assertRaises(ValueError): SuggestionRequest(training_mode='unknown',profile={})
