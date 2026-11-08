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
