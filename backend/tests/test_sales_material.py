import io
import unittest
from unittest.mock import AsyncMock, patch
from pypdf import PdfReader
from app.services.sales_material import research, MaterialRequest, render_material, search_key

class MaterialTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        async def roles(organization, product, needs, target):
            return dict(customer=organization, seller='', product=product, need=needs, target=target)
        patcher = patch('app.services.sales_material.identify_roles', side_effect=roles)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch('app.services.sales_material.summarize', new=AsyncMock(return_value=[]))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_digest_pdf_uses_same_insights_and_all_links(self):
        body = MaterialRequest(profile={'product':'数学课'}, background={
            'digest_version':1,
            'sources':[{'title':'不展示的零散结果','summary':'某老师履历','url':'https://example.org/raw'}],
            'insights':[{'title':'课程大纲','summary':'基础知识与综合训练。','caveat':'适用年级待确认。',
                'sources':[{'title':'学校资料','summary':'课程','url':'https://example.org/school'},
                           {'title':'产品资料','summary':'课程','url':'https://example.org/product'}]}]})
        reader = PdfReader(io.BytesIO(render_material(body)))
        text = ''.join(page.extract_text() for page in reader.pages)
        self.assertIn('基础知识与综合训练',text)
        self.assertNotIn('适用年级待确认',text)
        self.assertIn('信息可能不准确',text)
        self.assertNotIn('某老师履历',text)
        links = [str(a.get_object().get('/A',{}).get('/URI','')) for page in reader.pages for a in page.get('/Annots',[])]
        self.assertEqual(len(links),2)

    async def test_filters_wrong_entity_grade_and_subject_but_accepts_public_media(self):
        rows = [
            dict(title='上海中学高二数学试卷', snippet='上海中学高二数学课程试题', url='https://mp.weixin.qq.com/s/example', date='2026-09-01'),
            dict(title='上海中学高一数学', snippet='上海中学高一数学课程', url='https://example.org/grade'),
            dict(title='另一学校高二数学', snippet='另一学校高二数学课程', url='https://example.org/wrong'),
            dict(title='上海中学高二英语', snippet='上海中学英语课程', url='https://example.org/subject'),
        ]
        with patch('app.services.sales_material.search_via_mcp', new=AsyncMock(return_value=rows)), patch('app.services.sales_material.lookup_overview', new=AsyncMock(return_value=None)):
            result = await research('上海中学','数学拔高课','','高二学生家长')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['date'], '2026-09-01')
        self.assertIn('mp.weixin.qq.com', result['sources'][0]['publisher'])

    async def test_company_background_accepts_common_alias_without_fixed_profile_terms(self):
        rows = [dict(title='海底捞', snippet='海底捞以火锅餐饮服务为主要业务，并持续拓展门店。',
                     url='https://www.haidilao.com/about')]
        with patch('app.services.sales_material.search_via_mcp', new=AsyncMock(return_value=rows)):
            result = await research('海底捞国际控股有限公司', '企业差旅管理', '差旅预订与费用管理', '行政采购负责人')
        self.assertIsNotNone(result['overview'])
        self.assertEqual(result['overview']['url'], rows[0]['url'])

    async def test_explicit_prospect_organization_is_not_misclassified_as_seller(self):
        from app.services.research_digest import identify_roles
        organization = '海底捞国际控股有限公司'
        with patch('app.services.research_digest.ask_json', new=AsyncMock(return_value={
            'seller': organization, 'customer': ''})):
            roles = await identify_roles(organization, '企业差旅管理服务', '差旅费用管理', '行政采购负责人')
        self.assertEqual(roles['customer'], organization)
        self.assertEqual(roles['seller'], '')

    async def test_search_failure_still_returns_user_context_background(self):
        with patch('app.services.sales_material.search_via_mcp', new=AsyncMock(side_effect=RuntimeError())):
            result = await research('海底捞国际控股有限公司', '企业差旅管理', '差旅费用管理', '行政采购负责人')
        self.assertTrue(result['basic_background'])
        self.assertIn('海底捞国际控股有限公司', result['basic_background'])
        self.assertIn('不代表已核实', result['basic_background'])

    def test_pdf_shows_user_context_when_search_has_no_results(self):
        body = MaterialRequest(profile={'organization':'海底捞国际控股有限公司','product':'企业差旅管理'}, background={
            'digest_version':1, 'organization':'海底捞国际控股有限公司',
            'basic_background':'已知情景信息：机构/公司：海底捞国际控股有限公司；产品或服务：企业差旅管理。以上仅为使用者填写内容，不代表已核实的机构事实。'})
        reader = PdfReader(io.BytesIO(render_material(body)))
        text = ''.join(page.extract_text() for page in reader.pages)
        self.assertIn('海底捞国际控股有限公司', text)
        self.assertIn('不代表已核实', text)

    def test_price_objection_pdf_adds_price_preparation_without_inventing_discounts(self):
        body = MaterialRequest(training_mode='price_objection', profile={
            'product':'数学一对一课程','target':'高三家长','goal':'确认价格顾虑',
            'price_brand_a':'学而思','price_brand_b':'新东方',
            'price_comparison_aspect':'单课时价格',
            'price_concern':'客户认为学而思单课时价格比新东方贵，担心多出的费用不值得。'}, background={
            'digest_version':1, 'organization':'','basic_background':'用户填写的课程与对象信息。',
            'price_comparison':{'aspect':'单课时价格','entries':[
                {'slot':'A','brand':'学而思','evidence':[{'price':'600元','snippet':'学而思单课时约600元','title':'A课程页','url':'https://example.com/a'}]},
                {'slot':'B','brand':'新东方','evidence':[{'price':'450元','snippet':'新东方单课时约450元','title':'B课程页','url':'https://example.com/b'}]},
            ],'market_reference':[],'notice':'只使用明确出现的金额。'}})
        reader = PdfReader(io.BytesIO(render_material(body)))
        text = ''.join(page.extract_text() for page in reader.pages)
        self.assertIn('价格异议准备', text)
        self.assertIn('学而思', text)
        self.assertIn('新东方', text)
        self.assertIn('单课时价格', text)
        self.assertIn('600元', text)
        self.assertIn('450元', text)
        self.assertIn('不会自动推荐降价', text)
        self.assertIn('待核实', text)

    async def test_outage_has_no_invented_results(self):
        with patch('app.services.sales_material.search_via_mcp', new=AsyncMock(side_effect=RuntimeError())):
            result = await research('', '适老手机', '', '老人')
        self.assertEqual(result['sources'], [])
        self.assertTrue(result['gaps'])

    async def test_price_objection_research_adds_public_price_and_value_query(self):
        with patch('app.services.sales_material.identify_roles', new=AsyncMock(return_value={'seller':'示例机构','customer':''})) as identify, \
             patch('app.services.sales_material.make_plans', return_value=[]), \
             patch('app.services.sales_material.search_via_mcp', new=AsyncMock(return_value=[])) as search, \
             patch('app.services.sales_material.summarize', new=AsyncMock(return_value=[])) as summarize:
            await research('石家庄市第二中学', '数学一对一课程', '', '高三家长', 'price_objection',
                           '学而思', '新东方', '高途', '单课时价格')
        queries = '\n'.join(call.args[0] for call in search.await_args_list)
        self.assertIn('学而思', queries)
        self.assertIn('新东方', queries)
        self.assertIn('高途', queries)
        self.assertIn('单课时价格', queries)
        self.assertIn('市场 价格 区间', queries)
        self.assertIn('官网', queries)
        self.assertIn('公众号', queries)
        self.assertIn('石家庄', queries)
        identify.assert_not_awaited()
        summarize.assert_not_awaited()

    def test_school_aliases_cover_numbered_school_short_name(self):
        from app.services.research_digest import entity_aliases
        aliases = entity_aliases('石家庄市第二中学')
        self.assertIn('石家庄市第二中学', aliases)
        self.assertIn('石家庄二中', aliases)

    def test_price_evidence_keeps_explicit_amount_and_source_without_guessing(self):
        from app.services.sales_material import extract_price_evidence
        sources = [
            {'topic':'A品牌价格资料','summary':'学而思高三数学一对一单课时价格约600元，具体以校区为准。','title':'A课程页','url':'https://example.com/a','date':'2026-01-01'},
            {'topic':'B品牌价格资料','summary':'新东方同类课程单课时约450元。','title':'B课程页','url':'https://example.com/b','date':'2026-01-02'},
        ]
        evidence = extract_price_evidence(sources, 'A品牌价格资料')
        self.assertEqual(evidence[0]['price'], '600元')
        self.assertIn('学而思', evidence[0]['snippet'])
        self.assertEqual(evidence[0]['url'], 'https://example.com/a')
        self.assertEqual(extract_price_evidence(sources, 'C品牌价格资料'), [])

    def test_pdf_preserves_chinese_sources_and_escapes_markup(self):
        body = MaterialRequest(profile={'product':'数学课','target':'高二家长','goal':'试听'}, background={
            'organization':'','checked_at':'2026-11-12', 'notice':'公开检索摘要',
            'sources':[{'title':'课程介绍','summary':'数学课程 <重要> & 教学安排','url':'https://example.org/course','date':'2026-09-01'}]})
        result = render_material(body)
        reader = PdfReader(io.BytesIO(result))
        text = ''.join(p.extract_text() for p in reader.pages)
        self.assertIn('数学课', text)
        self.assertIn('高二家长', text)
        self.assertIn('<重要>', text)
        links = [str(a.get_object().get('/A',{}).get('/URI','')) for p in reader.pages for a in p.get('/Annots',[])]
        self.assertIn('https://example.org/course', links)

    def test_multiple_entities_are_queried_separately(self):
        from app.services.sales_material import queries
        plans = queries('学而思、松江二中','数学网课','','高二学生家长')
        self.assertTrue(any(p[2]=='松江二中' for p in plans))
        self.assertFalse(any('学而思、松江二中' in p[1] for p in plans))

    def test_stale_background_rejected(self):
        from app.api.v1.practice import preparation_material
        from fastapi import HTTPException
        body=MaterialRequest(profile={'product':'新产品'},background={'search_key':search_key('','旧产品','','')})
        with self.assertRaises(HTTPException) as error: preparation_material(body)
        self.assertEqual(error.exception.status_code, 422)
