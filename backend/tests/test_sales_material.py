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
        self.assertIn('适用年级待确认',text)
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

    async def test_outage_has_no_invented_results(self):
        with patch('app.services.sales_material.search_via_mcp', new=AsyncMock(side_effect=RuntimeError())):
            result = await research('', '适老手机', '', '老人')
        self.assertEqual(result['sources'], [])
        self.assertTrue(result['gaps'])

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
