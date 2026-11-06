import unittest
from unittest.mock import AsyncMock, patch
from app.services.preparation import PreparationProfile, collect_information, build_prepared_persona

class PreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_preserves_edits_and_limits_questions(self):
        profile = PreparationProfile(product='设备', target='采购经理', goal='预约演示')
        with patch('app.services.preparation.get_minimax_service') as factory:
            factory.return_value.chat = AsyncMock(return_value='{"industry":"制造业","product":"错误覆盖","organization":""}')
            result = await collect_information(profile, '制造业')
        self.assertEqual(result['profile']['product'], '设备')
        self.assertTrue(result['ready'])
        self.assertLessEqual(len(result['questions']), 2)

    async def test_unknown_can_be_filled_by_followup(self):
        with patch('app.services.preparation.get_minimax_service') as factory:
            factory.return_value.chat = AsyncMock(return_value='{"product":"设备"}')
            result = await collect_information(PreparationProfile(product='不清楚'), '推销设备')
        self.assertEqual(result['profile']['product'], '设备')

    async def test_extracts_wrapped_chinese_fields_after_reasoning(self):
        raw = '<think>示例 {不属于结果}</think>```json\n{"profile":{"产品或服务":"数学课","对象身份／职务":"初二家长","本次练习目标":"试听","喜好与顾虑":["担心效果","关注价格"]}}\n```'
        with patch('app.services.preparation.get_minimax_service') as factory:
            factory.return_value.chat = AsyncMock(return_value=raw)
            result = await collect_information(PreparationProfile(), '向初二家长推销数学课，希望试听')
        self.assertEqual(result['profile']['product'], '数学课')
        self.assertTrue(result['ready'])
        self.assertEqual(result['warning'], '')

    async def test_retries_unparseable_result(self):
        with patch('app.services.preparation.get_minimax_service') as factory:
            factory.return_value.chat = AsyncMock(side_effect=['', '{"product":"设备","target":"采购经理","goal":"演示"}'])
            result = await collect_information(PreparationProfile(), '向采购经理介绍设备，目标是演示')
        self.assertTrue(result['ready'])
        self.assertTrue(result['success'])

    async def test_offline_extracts_explicit_fields_without_inventing(self):
        with patch('app.services.preparation.get_minimax_service') as factory:
            factory.return_value.chat = AsyncMock(side_effect=RuntimeError('offline'))
            result = await collect_information(PreparationProfile(), '产品：数学课；对象：初二家长；目标：预约试听')
        self.assertEqual(result['profile']['product'], '数学课')
        self.assertEqual(result['profile']['target'], '初二家长')
        self.assertEqual(result['profile']['organization'], '')
        self.assertTrue(result['warning'])

    async def test_user_example_recovers_automatically_during_outage(self):
        with patch('app.services.preparation.get_minimax_service') as factory:
            factory.return_value.chat = AsyncMock(side_effect=RuntimeError('offline'))
            result = await collect_information(PreparationProfile(), '推销学而思数学课,推销对象是就读于上海中学的高二学生家长,家长想让孩子数学成绩提升至少20分')
        self.assertEqual(result['profile']['product'], '学而思数学课')
        self.assertEqual(result['profile']['target'], '高二学生家长')
        self.assertEqual(result['profile']['organization'], '上海中学')
        self.assertIn('20分', result['profile']['needs'])
        self.assertEqual(result['profile']['goal'], '')
        self.assertFalse(result['success'])

    async def test_background_requires_source_url(self):
        from app.services.preparation import lookup_background
        with patch('app.services.preparation.search_via_mcp', new=AsyncMock(return_value=[{'title':'无来源'}, {'title':'官网','url':'https://example.com','snippet':'主营设备'}])):
            result = await lookup_background('示例公司')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['organization'], '示例公司')

    async def test_failure_keeps_manual_values(self):
        profile = PreparationProfile(product='课程')
        with patch('app.services.preparation.get_minimax_service') as factory:
            factory.return_value.chat = AsyncMock(side_effect=RuntimeError('offline'))
            result = await collect_information(profile, '一些介绍')
        self.assertEqual(result['profile']['product'], '课程')
        self.assertFalse(result['ready'])
        self.assertTrue(result['warning'])

    def test_personal_customer_has_no_invented_company(self):
        profile = PreparationProfile(product='数学课', target='初二家长', goal='试听')
        persona = build_prepared_persona(profile.model_dump())
        self.assertEqual(persona['title'], '初二家长')
        self.assertEqual(persona['company'], '')
        self.assertEqual(persona['concerns'], [])
        self.assertIn('数学课', persona['scenario_context'])
        self.assertIn('试听', persona['scenario_context'])

    def test_background_is_matched_to_current_organization(self):
        data = PreparationProfile(product='设备', target='采购经理', goal='演示', organization='示例公司').model_dump()
        background = {'organization':'示例公司','sources':[{'title':'官网','summary':'主营制造','url':'https://example.com'}]}
        self.assertIn('主营制造', build_prepared_persona(data, background)['background'])
        data['organization'] = '另一公司'
        self.assertNotIn('主营制造', build_prepared_persona(data, background)['background'])

    async def test_sales_background_filters_unrelated_results(self):
        from app.services.preparation import lookup_background
        rows = [
            {'title':'上海中学数学教学','snippet':'数学学习课程','url':'https://example.com/math'},
            {'title':'上海中学校门维修','snippet':'招标公告','url':'https://example.com/gate'},
            {'title':'其他学校数学教学','snippet':'课程','url':'https://example.com/other'},
        ]
        with patch('app.services.preparation.search_via_mcp', new=AsyncMock(return_value=rows)) as search:
            result = await lookup_background('上海中学', '数学课', '提高数学成绩')
        self.assertEqual([s['url'] for s in result['sources']], ['https://example.com/math'])
        self.assertTrue(any('数学课' in call.args[0] for call in search.call_args_list))

    async def test_institution_intro_excludes_reviews_and_limits_four(self):
        from app.services.preparation import lookup_background
        rows = [{'title':'上海中学数学课用户评价','snippet':'数学课程口碑','url':'https://example.com/review'}]
        rows += [{'title':f'上海中学数学教学{i}','snippet':'数学课程介绍' + '教学安排'*80,'url':f'https://example.com/{i}'} for i in range(6)]
        rows.insert(2, rows[1])
        with patch('app.services.preparation.search_via_mcp', new=AsyncMock(return_value=rows)) as search:
            result = await lookup_background('上海中学', '学而思数学课', '提高成绩')
        self.assertEqual(len(result['sources']), 4)
        self.assertEqual(len({s['url'] for s in result['sources']}), 4)
        self.assertFalse(any('评价' in s['title'] for s in result['sources']))
        self.assertTrue(all(len(s['summary']) <= 120 for s in result['sources']))
        self.assertNotIn('学而思', search.call_args.args[0])

    async def test_overview_is_separate_from_sales_facts(self):
        from app.services.preparation import lookup_background
        async def search(query, count):
            if '背景概况' in query:
                return [{'title':'上海中学学校简介','snippet':'上海中学是上海市实验性示范性高中。','url':'https://example.edu/intro'}]
            return [{'title':'上海中学数学课程','snippet':'数学课程教学安排','url':'https://example.edu/math'}]
        with patch('app.services.preparation.search_via_mcp', new=AsyncMock(side_effect=search)):
            result = await lookup_background('上海中学', '数学课')
        self.assertIn('示范性高中', result['overview']['summary'])
        self.assertEqual(len(result['sources']), 1)

    async def test_overview_does_not_invent_rank_without_year(self):
        from app.services.preparation import lookup_overview
        with patch('app.services.preparation.search_via_mcp', new=AsyncMock(return_value=[{'title':'示例公司世界500强','snippet':'示例公司排名第一','url':'https://example.com'}])):
            result = await lookup_overview('示例公司')
        self.assertIsNone(result)

    def test_whitespace_not_ready(self):
        self.assertFalse(PreparationProfile(product=' ', target='客户', goal='成交').ready)

if __name__ == '__main__':
    unittest.main()
