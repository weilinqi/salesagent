"""Bounded Chinese lexical/semantic retrieval with optional public web evidence."""
import asyncio
import re
from urllib.parse import urlsplit


SYNONYMS = (
    ('嫌贵', '太贵', '价格异议', '预算不足', '价格谈判'),
    ('客户需求', '需求挖掘', '需求分析', '痛点'),
    ('竞品', '竞争对手', '竞争分析'),
    ('成交', '促成交易', '签约'),
    ('spin', '顾问式销售', '情境问题', '难点问题', '暗示问题', '需求效益问题'),
)


def expanded_terms(query: str) -> list[str]:
    query = query.strip().lower()
    terms = [query]
    for group in SYNONYMS:
        if any(term in query for term in group):
            terms.extend(group)
    terms.extend(re.findall(r'[a-z0-9][a-z0-9._-]*', query))
    # Chinese has no whitespace boundaries. Bigrams also match unlisted terms.
    for segment in re.findall(r'[\u4e00-\u9fff]+', query):
        terms.extend(segment[i:i + 2] for i in range(len(segment) - 1))
    return list(dict.fromkeys(term for term in terms if term))[:12]


def fuse_results(semantic: list, lexical: list, request) -> list:
    rows, ranks = {}, {}
    seen_content = set()
    for results in (semantic, lexical):
        seen_ids = set()
        for rank, row in enumerate(results, 1):
            if request.category and row.get('metadata', {}).get('category') != request.category:
                continue
            if request.source_filter and row.get('source') != request.source_filter:
                continue
            cid = row['id']
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            previous = rows.get(cid)
            preferred = previous if previous and len(previous.get('text', '')) > len(row.get('text', '')) else row
            rows[cid] = {**preferred, 'score': max(row.get('score', 0), (previous or {}).get('score', 0))}
            ranks[cid] = ranks.get(cid, 0) + 1 / (60 + rank)
    # Legacy ingestion can leave multiple IDs with the same chapter/prefix.
    # Prefer the complete text while keeping the highest-ranked position.
    content_rows = {}
    for row in rows.values():
        key = (row.get('source'), row.get('metadata', {}).get('chapter', ''), row.get('text', '')[:80])
        previous = content_rows.get(key)
        if previous is None or len(row.get('text', '')) > len(previous.get('text', '')):
            content_rows[key] = row
    output = []
    for cid in sorted(rows, key=lambda key: ranks[key], reverse=True):
        row = rows[cid]
        fingerprint = (row.get('source'), row.get('metadata', {}).get('chapter', ''), row.get('text', '')[:80])
        if fingerprint in seen_content:
            continue
        seen_content.add(fingerprint)
        output.append(content_rows[fingerprint])
        if len(output) >= request.top_k:
            break
    return output


def safe_web_results(rows: list, limit: int) -> list:
    output, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get('url', '')
        if not isinstance(url, str) or any(char.isspace() for char in url):
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        output.append({'url': url, 'title': str(row.get('title') or '')[:200],
                       'snippet': str(row.get('snippet') or '')[:2000],
                       'date': str(row.get('date') or '')[:100]})
        if len(output) >= limit:
            break
    return output


async def hybrid_search(request, semantic_search, keyword_search, web_search) -> dict:
    notices, semantic, lexical = [], [], []
    local_failed = False
    if request.mode != 'web':
        values = await asyncio.gather(semantic_search(request), keyword_search(request), return_exceptions=True)
        local_failed = all(isinstance(value, Exception) for value in values)
        semantic = values[0] if isinstance(values[0], list) else []
        lexical = values[1] if isinstance(values[1], list) else []
        if any(isinstance(value, Exception) for value in values):
            notices.append('本地部分检索暂不可用，已保留可用结果。请检查模型和文档入库状态。')
    local = fuse_results(semantic, lexical, request)
    # Similarity is not a probability. This is a conservative routing heuristic,
    # configurable later against a labeled evaluation set, not a confidence claim.
    local_ids = {row['id'] for row in local}
    strong = (any(row['id'] in local_ids and row.get('score', 0) >= 0.75 for row in semantic)
              or any(row['id'] in local_ids and row.get('_query_coverage', 0) >= 0.75 for row in lexical))
    filtered = bool(request.source_filter or request.category)
    use_web = request.mode == 'web' or (request.mode == 'auto' and not strong and not filtered)
    web = []
    if use_web:
        try:
            rows = await asyncio.wait_for(web_search(request.query, min(request.top_k, 10)), timeout=12)
            web = safe_web_results(rows, request.top_k)
            if not web:
                notices.append('联网搜索没有找到可展示的来源，请尝试更具体的关键词。')
        except Exception:
            notices.append('MiniMax 联网搜索暂不可用，请检查搜索密钥、搜索权限或网络后重试。本地结果仍可使用。')
    if local_failed and not web:
        notices.append('本地知识库检索不可用，且没有可展示的联网结果；请检查知识库索引、搜索密钥和网络配置。')
    return {'results': local, 'query': request.query, 'total': len(local),
            'web_results': web, 'notices': notices, 'mode': request.mode}
