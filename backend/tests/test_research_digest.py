import unittest
from unittest.mock import AsyncMock, patch
from app.services.research_digest import identify_roles, make_plans, summarize


class DigestTests(unittest.IsolatedAsyncioTestCase):
    async def test_roles_and_linked_school_plan(self):
        with patch('app.services.research_digest.ask_json', new=AsyncMock(return_value={
            'seller': '学而思', 'customer': '松江二中', 'product': '数学网课', 'need': '高二数学提升'})):
            roles = await identify_roles('学而思、松江二中', '数学网课', '数学提升', '高二学生家长')
        self.assertEqual(roles['customer'], '松江二中')
        plans = make_plans(roles)
        self.assertTrue(any('学而思' in p[1] and '高二' in p[1] for p in plans))
        self.assertTrue(any(p[2] == '松江二中' for p in plans))
        self.assertFalse(any(p[0] == '学而思' for p in plans))

    async def test_digest_bound_and_citations_resolved_from_evidence(self):
        sources = [dict(title='课程体系', summary='高二数学课程大纲', url='https://example.org/a'),
                   dict(title='课程介绍', summary='数学模块', url='https://example.org/b')]
        entries = [dict(title=f'方面{i}', summary=f'方面{i}的课程内容。', source_ids=[0, 1], caveat='') for i in range(7)]
        entries.insert(0, dict(title='伪造来源', summary='无依据', source_ids=[99]))
        with patch('app.services.research_digest.ask_json', new=AsyncMock(return_value={'items': entries})):
            items = await summarize({'customer':'松江二中'}, sources)
        self.assertEqual(len(items), 5)
        self.assertEqual(len(items[0]['sources']), 2)
        self.assertEqual(items[0]['sources'][1]['url'], sources[1]['url'])

    async def test_failure_does_not_masquerade_as_synthesis(self):
        with patch('app.services.research_digest.ask_json', new=AsyncMock(side_effect=TimeoutError())):
            self.assertEqual(await summarize({}, [dict(title='资料', summary='摘要', url='https://example.org')]), [])

    async def test_roles_do_not_invent_institution(self):
        with patch('app.services.research_digest.ask_json', new=AsyncMock(return_value={'customer':'虚构学校', 'seller':'虚构品牌'})):
            roles = await identify_roles('', '手机', '', '老人')
        self.assertEqual(roles['customer'], '')
        self.assertEqual(roles['seller'], '')
