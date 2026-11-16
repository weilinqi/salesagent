"""Offline knowledge retrieval, routing and validation regressions."""
import unittest
from unittest.mock import AsyncMock

from pydantic import ValidationError
from app.schemas.knowledge import KnowledgeSearchRequest
from app.services.rag.hybrid_search import expanded_terms, hybrid_search
from app.services.rag.vector_store import VectorStore


def row(cid='one', score=0.8):
    return {'id': cid, 'text': '价格异议处理', 'source': 'sales.pdf',
            'score': score, 'metadata': {'category': 'spin'}}


class HybridSearchTests(unittest.IsolatedAsyncioTestCase):
    async def run_search(self, mode='local', semantic=None, lexical=None, web=None, **kwargs):
        self.semantic = semantic or AsyncMock(return_value=[row()])
        self.lexical = lexical or AsyncMock(return_value=[row()])
        self.web = web or AsyncMock(return_value=[])
        return await hybrid_search(KnowledgeSearchRequest(query='客户嫌贵', mode=mode, **kwargs),
                                   self.semantic, self.lexical, self.web)

    def test_chinese_synonyms_and_model_numbers(self):
        self.assertIn('价格异议', expanded_terms('客户嫌贵'))
        self.assertIn('x100', expanded_terms('X100'))
        self.assertLessEqual(len(expanded_terms('很长的中文问题' * 50)), 12)

    def test_reject_blank_long_and_unknown_mode(self):
        for values in ({'query': '   '}, {'query': 'a' * 501}, {'query': 'sales', 'mode': 'unknown'}):
            with self.assertRaises(ValidationError):
                KnowledgeSearchRequest(**values)

    async def test_default_local_deduplicates_without_network(self):
        result = await self.run_search()
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(result['results'][0]['id'], 'one')
        self.web.assert_not_awaited()

    async def test_auto_uses_web_for_weak_semantic_matches(self):
        web = AsyncMock(return_value=[{'title': 'Official', 'url': 'https://example.com', 'snippet': 'Evidence'}])
        result = await self.run_search('auto', semantic=AsyncMock(return_value=[row(score=0.1)]),
                                       lexical=AsyncMock(return_value=[]), web=web)
        self.assertEqual(len(result['web_results']), 1)
        web.assert_awaited_once()

    async def test_strong_local_result_skips_web(self):
        await self.run_search('auto')
        self.web.assert_not_awaited()

    async def test_source_filter_never_triggers_web_automatically(self):
        await self.run_search('auto', semantic=AsyncMock(return_value=[]),
                              lexical=AsyncMock(return_value=[]), source_filter='one.pdf')
        self.web.assert_not_awaited()

    async def test_local_failure_retains_keyword_result(self):
        result = await self.run_search(semantic=AsyncMock(side_effect=RuntimeError('private error')))
        self.assertEqual(len(result['results']), 1)
        self.assertTrue(result['notices'])
        self.assertNotIn('private error', str(result))

    async def test_both_local_failures_are_visible(self):
        with self.assertRaises(RuntimeError):
            await self.run_search(semantic=AsyncMock(side_effect=RuntimeError()),
                                  lexical=AsyncMock(side_effect=RuntimeError()))

    async def test_web_failure_retains_local_results_and_safe_notice(self):
        result = await self.run_search('auto', semantic=AsyncMock(return_value=[row(score=0.1)]),
                                       lexical=AsyncMock(return_value=[]),
                                       web=AsyncMock(side_effect=RuntimeError('private token')))
        self.assertEqual(len(result['results']), 1)
        self.assertTrue(result['notices'])
        self.assertNotIn('private token', str(result))

    async def test_web_only_skips_local_and_rejects_unsafe_duplicate_urls(self):
        web = AsyncMock(return_value=[{'url': 'javascript:alert(1)'},
            {'url': 'https://example.com', 'title': 'A'}, {'url': 'https://example.com', 'title': 'B'}])
        result = await self.run_search('web', web=web)
        self.semantic.assert_not_awaited()
        self.lexical.assert_not_awaited()
        self.assertEqual(len(result['web_results']), 1)

    async def test_category_filter_and_limit_apply_to_both_rankings(self):
        wrong = {**row('wrong'), 'metadata': {'category': 'other'}}
        result = await self.run_search(semantic=AsyncMock(return_value=[wrong, row()]),
                                      lexical=AsyncMock(return_value=[wrong, row()]), category='spin', top_k=1)
        self.assertEqual([item['id'] for item in result['results']], ['one'])

    async def test_synonym_only_score_does_not_suppress_web(self):
        lexical = {**row(), 'text': '竞争分析', 'score': 1, '_query_coverage': 0}
        web = AsyncMock(return_value=[])
        await hybrid_search(KnowledgeSearchRequest(query='竞品价格', mode='auto'),
                            AsyncMock(return_value=[row(score=0.1)]),
                            AsyncMock(return_value=[lexical]), web)
        web.assert_awaited_once()

    async def test_legacy_duplicate_prefix_prefers_longer_record(self):
        prefix = 'A' * 80
        short = {**row('short'), 'text': prefix, 'metadata': {'chapter': '1'}}
        long = {**row('long'), 'text': prefix + ' additional evidence', 'metadata': {'chapter': '1'}}
        result = await self.run_search(semantic=AsyncMock(return_value=[short, long]),
                                      lexical=AsyncMock(return_value=[]))
        self.assertEqual([item['id'] for item in result['results']], ['long'])


class LexicalStoreTests(unittest.TestCase):
    def test_original_case_model_token_is_searched_in_multiword_query(self):
        class Collection:
            def get(self, **kwargs):
                if kwargs['where_document']['$contains'] == 'X100':
                    return {'ids': ['model'], 'documents': ['X100 product coverage'],
                            'metadatas': [{'source': 'models.pdf'}]}
                return {'ids': [], 'documents': [], 'metadatas': []}
        store = VectorStore()
        store._collection = Collection()
        self.assertEqual(store.keyword_search('X100 warranty')[0]['id'], 'model')

    def test_chinese_synonym_candidates_are_filtered_before_limit(self):
        calls = []

        class Collection:
            def get(self, **kwargs):
                calls.append(kwargs)
                if kwargs['where_document']['$contains'] == '价格异议':
                    return {'ids': ['one'], 'documents': ['处理价格异议的方法'],
                            'metadatas': [{'source': 'sales.pdf', 'category': 'spin'}]}
                return {'ids': [], 'documents': [], 'metadatas': []}

        store = VectorStore()
        store._collection = Collection()
        result = store.keyword_search('客户嫌贵', source_filter='sales.pdf', category='spin')
        self.assertEqual(result[0]['id'], 'one')
        self.assertTrue(all(call['where'] == {'$and': [{'source': 'sales.pdf'}, {'category': 'spin'}]} for call in calls))
        self.assertTrue(all(call['limit'] == 100 for call in calls))
        self.assertLessEqual(len(calls), 13)


if __name__ == '__main__':
    unittest.main()
