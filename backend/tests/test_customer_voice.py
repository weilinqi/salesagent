import unittest
from app.services.conversation.customer_voice import audience, opening, dialogue_rules

class CustomerVoiceTests(unittest.TestCase):
    def test_personal_roles_are_not_corporate_buyers(self):
        for title in ('老人', '学生家长', '退休教师'):
            persona = {'title': title, 'company': '某公司'}
            self.assertEqual(audience(persona), 'personal')
            self.assertNotIn('选型', opening(persona))
    def test_personal_purchase_overrides_job(self):
        self.assertEqual(audience({'title':'工程师', 'scenario_context':'给孩子购买手机'}), 'personal')
    def test_professional_and_unknown(self):
        self.assertEqual(audience({'title':'采购经理'}), 'professional')
        self.assertEqual(audience({'company':'某公司'}), 'neutral')
    def test_rules_cover_followup_and_no_stereotypes(self):
        rules = dialogue_rules({'title':'老人'})
        self.assertIn('已回答清楚的问题不重复追问', rules)
        self.assertIn('不推断收入', rules)


class ContextualOpeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_opening_receives_product_identity_and_need(self):
        from unittest.mock import AsyncMock
        from app.services.preparation import build_prepared_persona
        from app.services.conversation.customer_voice import generate_customer_opening
        persona = build_prepared_persona({'product':'数学拔高课','target':'高二学生家长','needs':'数学提高20分','goal':'介绍课程'})
        chat = AsyncMock(return_value='这门数学课会先了解孩子哪些地方需要加强吗？')
        result = await generate_customer_opening(persona, chat)
        prompt = chat.call_args.kwargs['messages'][0]['content']
        for fact in ('数学拔高课', '高二学生家长', '数学提高20分'):
            self.assertIn(fact, prompt)
        self.assertEqual(result, chat.return_value)
        self.assertIn('资料已给出的年级', dialogue_rules(persona))

    async def test_outage_keeps_product_without_inventing_claims(self):
        from unittest.mock import AsyncMock
        from app.services.conversation.customer_voice import generate_customer_opening
        result = await generate_customer_opening({'title':'老人','product':'智能手机'}, AsyncMock(side_effect=RuntimeError()))
        self.assertIn('智能手机', result)
        self.assertNotIn('项目', result)
