"""Targeted public search and bounded, source-linked sales preparation PDFs."""
import asyncio
import io
import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlsplit
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl
from app.services.preparation import PreparationProfile, LABELS, lookup_overview
from app.services.search import search_via_mcp, SearchUnavailable
from app.services.research_digest import identify_roles, make_plans, summarize, entity_matches, entity_aliases

class MaterialSource(BaseModel):
    title: str = Field(max_length=300)
    summary: str = Field(max_length=2000)
    url: HttpUrl
    date: str = Field(default='', max_length=100)
    publisher: str = Field(default='', max_length=200)
    topic: str = Field(default='', max_length=100)

class MaterialInsight(BaseModel):
    title: str = Field(max_length=60)
    summary: str = Field(max_length=220)
    caveat: str = Field(default='', max_length=300)
    sources: list[MaterialSource] = Field(min_length=1, max_length=12)

class MaterialBackground(BaseModel):
    roles: dict[str, str] = Field(default_factory=dict)
    insights: list[MaterialInsight] = Field(default_factory=list, max_length=5)
    digest_version: int = 0
    organization: str = Field(default='', max_length=1000)
    overview: MaterialSource | None = None
    sources: list[MaterialSource] = Field(default_factory=list, max_length=12)
    notice: str = Field(default='', max_length=1000)
    checked_at: str = Field(default='', max_length=100)
    gaps: list[str] = Field(default_factory=list, max_length=10)
    search_key: str = Field(default='', max_length=5000)
    basic_background: str = Field(default='', max_length=1200)
    price_comparison: dict = Field(default_factory=dict)

class MaterialRequest(BaseModel):
    profile: PreparationProfile
    background: MaterialBackground
    training_mode: Literal['full', 'rejection', 'price_objection', 'follow_up'] = 'full'

def search_key(organization, product, needs, target):
    return '\n'.join(x.strip() for x in (organization, product, needs, target))


PRICE_PATTERN = re.compile(r'(?:¥|￥)\s*\d+(?:\.\d+)?(?:\s*元)?|\d+(?:\.\d+)?\s*(?:万元|元\s*/\s*(?:课时|小时|年|学期|期|月)|元|万)')


def extract_price_evidence(sources, topic, limit=4):
    evidence, seen = [], set()
    for source in sources:
        if not str(source.get('topic', '')).startswith(topic):
            continue
        summary = str(source.get('summary', ''))
        for match in PRICE_PATTERN.finditer(summary):
            price = match.group().strip()
            key = (price, source.get('url', ''))
            if key in seen:
                continue
            seen.add(key)
            start, end = max(0, match.start() - 45), min(len(summary), match.end() + 55)
            evidence.append({
                'price': price[:80],
                'snippet': summary[start:end].strip()[:180],
                'title': str(source.get('title', '价格来源'))[:200],
                'url': str(source.get('url', '')),
                'date': str(source.get('date', ''))[:100],
            })
            if len(evidence) >= limit:
                return evidence
    return evidence


def _price_insights(entries, market_reference, price_aspect):
    insights = []
    for entry in entries:
        evidence = entry.get('evidence') or []
        brand = entry.get('brand') or '未填写品牌'
        slot = entry.get('slot') or ''
        prices = list(dict.fromkeys(item.get('price') for item in evidence if item.get('price')))
        if prices:
            summary = f"{slot}｜{brand}：检索到明确价格 {'、'.join(prices[:6])}；比较方面为{price_aspect}。"
        else:
            summary = f"{slot}｜{brand}：暂未检索到明确金额，建议查看品牌官网、公众号或重新检索；不会自动补造。"
        insights.append({
            'title': f"{slot}品牌价格｜{brand}"[:60],
            'summary': summary[:220],
            'caveat': '价格来自公开检索摘要，具体班型、校区和有效期请核对来源原文。',
            'sources': [
                {'title': item.get('title', '价格来源'), 'summary': item.get('snippet', ''),
                 'url': item.get('url', ''), 'date': item.get('date', '')}
                for item in evidence if item.get('url')
            ],
        })
    if market_reference:
        prices = list(dict.fromkeys(item.get('price') for item in market_reference if item.get('price')))
        insights.append({
            'title': '行业市场参考价',
            'summary': f"检索到公开市场参考金额：{'、'.join(prices[:6])}；不代表 A/B 官方报价，比较方面为{price_aspect}。",
            'caveat': '市场参考价可能包含不同班型或地区，不能直接当作某品牌官方价格。',
            'sources': [
                {'title': item.get('title', '市场参考来源'), 'summary': item.get('snippet', ''),
                 'url': item.get('url', ''), 'date': item.get('date', '')}
                for item in market_reference if item.get('url')
            ],
        })
    return insights[:5]


def _school_insights(sources):
    return [
        {
            'title': str(source.get('title', '学校公开资料'))[:60],
            'summary': str(source.get('summary', '暂无可核验摘要'))[:220],
            'caveat': '来自公开检索摘要；学校官网、公众号和最新招生安排请以原文为准。',
            'sources': [source],
        }
        for source in sources
        if source.get('topic') == '机构背景'
    ][:5]

def entities(organization):
    return list(dict.fromkeys(x.strip() for x in re.split(r'[、,，;；\n]+', organization) if x.strip()))[:3]


def queries(organization, product, needs, target):
    subjects = [s for s in ('数学','英语','语文','物理','化学','生物') if s in product]
    grade = re.findall(r'高[一二三]|初[一二三]|[一二三四五六]年级', target + needs)
    scope = ' '.join(subjects) or product
    plans = []
    for organization in entities(organization):
        plans.append(('机构相关资料', f'"{organization}" {scope} {" ".join(grade)} 课程 教学 试题' if subjects else f'"{organization}" {scope} 业务 应用', organization, subjects))
        if subjects:
            plans.append(('课程与难度线索', f'"{organization}" {scope} {" ".join(grade)} 教材 教学进度 试卷 难度', organization, subjects))
    if product:
        plans.append(('产品资料', f'"{product}" {needs[:120]} 产品介绍 适用范围', product, []))
    return plans

async def research(organization='', product='', needs='', target='', training_mode='full',
                   price_brand_a='', price_brand_b='', price_brand_c='', price_comparison_aspect=''):
    price_aspect = price_comparison_aspect or '价格'
    if training_mode == 'price_objection':
        roles = {
            'seller': price_brand_a,
            'customer': organization,
            'product': product,
            'need': needs,
            'target': target,
        }
        price_plans = []
        brands = (
            ('A品牌价格资料', price_brand_a),
            ('B品牌价格资料', price_brand_b),
            ('C品牌价格资料', price_brand_c),
        )
        if organization:
            for alias in entity_aliases(organization)[:3]:
                price_plans.append(('机构背景', f'"{alias}" 官网 学校简介 办学 高考 教学', organization, []))
            price_plans.append(('机构背景', f'{organization} 公众号 学校新闻 校园 动态', organization, []))
        for label, brand in brands:
            if brand:
                price_plans.append((label, f'"{brand}" "{product[:100]}" {price_aspect[:100]} 官网 价格 收费', brand, []))
                price_plans.append((label, f'{brand} {product[:100]} {price_aspect[:100]} 公众号 收费标准 课时费', brand, []))
                subject = next((item for item in ('数学', '英语', '语文', '物理', '化学', '生物') if item in product), '')
                if subject:
                    price_plans.append((label, f'{brand} 高考{subject} 一对一 收费 课时费 价格', brand, []))
        if product:
            price_plans.append(('市场参考价', f'"{product[:100]}" {price_aspect[:100]} 市场 价格 区间 平台 公众号', product, []))
            price_plans.append(('市场参考价', f'{product[:100]} 高考 一对一 收费标准 课时费 参考价', product, []))
        plan_priority = {'机构背景': -1, 'A品牌价格资料': 0, 'B品牌价格资料': 1, '市场参考价': 2, 'C品牌价格资料': 3}
        price_plans.sort(key=lambda plan: plan_priority.get(plan[0], 9))
        plans = price_plans
    else:
        roles = await identify_roles(organization, product, needs, target)
        plans = make_plans(roles)
    async def search(plan):
        try:
            return await asyncio.wait_for(search_via_mcp(plan[1], 10), 12)
        except SearchUnavailable as exc:
            return str(exc)
        except asyncio.TimeoutError:
            return '搜索超时，请稍后重试。'
        except Exception:
            return '搜索连接失败，请稍后重试。'
    outcomes = await asyncio.gather(*(search(p) for p in plans))
    overview = None
    customer = roles.get('customer')
    if customer and training_mode != 'price_objection':
        background_rows = [row for plan, rows in zip(plans, outcomes)
                           if plan[0] == '机构背景' and isinstance(rows, list)
                           for row in rows]
        overview = await lookup_overview(customer, background_rows)
    sources, gaps, seen = [], [], set()
    grades = set(re.findall(r'高[一二三]|初[一二三]|[一二三四五六]年级', target + needs))
    for plan, rows in zip(plans, outcomes):
        found = 0
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict): continue
            title, summary = str(row.get('title','')), str(row.get('snippet',''))
            corpus = title + ' ' + summary
            if plan[0] == '通用课程参考' and not any(t in corpus for t in ('课程标准', '教学大纲', '学习目标', '教育部', '教育委员会')): continue
            if plan[0] == '机构背景' and not any(t in corpus for t in (
                '简介', '概况', '成立', '主营', '培养', '示范', '重点', '办学', '校史', '招生', '发展',
                '总部', '品牌', '上市', '门店', '经营', '规模', '集团', '业务', '餐饮', '火锅', '汽车',
                '新能源', '航空', '航线', '客运', '物流', '制造', '研发', '能源', '创办', '沿革', '学校介绍')): continue
            url = row.get('url') or row.get('link') or ''
            parts = urlsplit(url) if isinstance(url, str) else None
            if not parts or parts.scheme not in ('https','http') or not parts.hostname or not summary: continue
            # Exact supplied entity/product name; never accept a partial same-name match.
            if plan[2] and not entity_matches(plan[2], corpus): continue
            if plan[3] and not any(s in corpus for s in plan[3]): continue
            row_grades = set(re.findall(r'高[一二三]|初[一二三]|[一二三四五六]年级', corpus))
            if plan[0] not in ('产品资料', '课程衔接', '产品适配', '机构背景') and grades and row_grades and not grades.intersection(row_grades): continue
            if any(s in corpus for s in ('用户评价','产品评价','口碑','好评','差评','投诉','避雷')): continue
            canonical = url.split('#')[0].rstrip('/')
            if canonical in seen: continue
            seen.add(canonical); found += 1
            sources.append(dict(title=title[:300], summary=summary[:1200], url=url,
                date=str(row.get('date') or '')[:100], publisher=parts.hostname,
                topic=plan[0]))
            if found >= (1 if training_mode == 'price_objection' else (3 if len(plans) > 3 else 4)): break
        if not found:
            gaps.append(plan[0] + ('：' + rows if isinstance(rows, str) else '：暂无同时匹配关键词的公开资料。'))
    if any(s in product for s in ('数学','英语','语文','物理','化学','生物')):
        gaps.append('课程难度需核对课程或试题原文；不能根据学校名气或检索摘要推断。')
    price_comparison = {}
    if training_mode == 'price_objection':
        entries = []
        for slot, brand, topic in (
            ('A', price_brand_a, 'A品牌价格资料'),
            ('B', price_brand_b, 'B品牌价格资料'),
            ('C', price_brand_c, 'C品牌价格资料'),
        ):
            if brand:
                entries.append({'slot': slot, 'brand': brand, 'evidence': extract_price_evidence(sources, topic)})
        market_reference = extract_price_evidence(sources, '市场参考价')
        price_comparison = {
            'aspect': price_aspect,
            'entries': entries,
            'market_reference': market_reference,
            'organized': [item['summary'] for item in _price_insights(entries, market_reference, price_aspect)],
            'notice': '已按 A/B 品牌分别整理明确出现的金额；单位不一致时不自动计算差价，未出现的品牌价格不会由模型补造。',
        }
        school_sources = [source for source in sources if source.get('topic') == '机构背景']
        insights = _school_insights(school_sources)
        if not school_sources:
            gaps.append('学校背景：暂未检索到可核验的公开资料，请检查学校全称或重新检索。')
    else:
        insights = await summarize(roles, sources[:12])
    if sources and not insights:
        gaps.append('已检索到资料，但暂未完成可靠概括，请重试；未将零散摘要充作整理结果。')
    return dict(organization=roles.get('customer') or organization, overview=overview,
        roles=roles, insights=insights, digest_version=1, sources=sources[:12], gaps=list(dict.fromkeys(gaps))[:10],
        basic_background=('公开资料尚未提供可核验的机构背景时，当前已知情景信息为：' +
            '；'.join(f'{label}：{value.strip()}' for label, value in (
                ('机构/公司', organization), ('产品或服务', product), ('对象身份', target), ('需求与场景', needs))
                if value and value.strip()) +
            '。以上仅为使用者填写内容，不代表已核实的机构事实。'),
        checked_at=datetime.now(timezone.utc).isoformat(), search_key=search_key(organization,product,needs,target),
        price_comparison=price_comparison,
        notice='围绕客户机构、产品和需求整合，最多5个方面；依据公开检索摘要，未逐篇核实原文。各条保留出处，适用范围及最新安排请以原文为准。')

def render_material(body: MaterialRequest):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from app.services.report_pdf import _register_chinese_font
    font = _register_chinese_font()
    if font == 'Helvetica':
        raise ValueError('未找到可用的中文字体，请安装中文字体后重试。')
    style = ParagraphStyle('Material', fontName=font, fontSize=10, leading=17, wordWrap='CJK', spaceAfter=8)
    heading = ParagraphStyle('Heading', parent=style, fontSize=15, leading=23, spaceBefore=12)
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42, title='销售准备资料')
    story = [Paragraph('销售准备资料', heading)]
    def para(text): return Paragraph(escape(str(text)).replace('\n','<br/>'), style)
    story.append(para('查询时间：' + body.background.checked_at))
    story.append(Paragraph('一、用户确认的信息', heading))
    profile_values = body.profile.model_dump()
    display_labels = dict(LABELS)
    display_keys = list(profile_values)
    if body.training_mode == 'price_objection':
        display_labels.update({
            'target': '客户身份／职务',
            'organization': '客户所属机构／关联人物',
            'product': '比较的产品或班型',
        })
        display_keys = ['target', 'organization', 'industry', 'product', 'goal']
    for key in display_keys:
        story.append(para(display_labels[key] + '：' + (profile_values[key] or '未填写')))
    if body.training_mode == 'price_objection':
        story.append(Paragraph('二、价格异议准备', heading))
        story.append(para('A 品牌：' + (body.profile.price_brand_a or '未填写')))
        story.append(para('B 品牌：' + (body.profile.price_brand_b or '未填写')))
        if body.profile.price_brand_c:
            story.append(para('C 品牌：' + body.profile.price_brand_c))
        story.append(para('价格比较方面：' + (body.profile.price_comparison_aspect or '未填写')))
        story.append(para('客户的具体价格顾虑：' + (body.profile.price_concern or '未填写')))
        story.append(para('先分别核对 A、B（以及 C）在同一产品/班型和同一价格比较方面上的公开价格，再比较；无法直接比较时不得强行计算差价。'))
        comparison = body.background.price_comparison or {}
        for entry in comparison.get('entries', []) if isinstance(comparison, dict) else []:
            if not isinstance(entry, dict):
                continue
            evidence = entry.get('evidence') if isinstance(entry.get('evidence'), list) else []
            story.append(para(f"{entry.get('slot', '')} 品牌｜{entry.get('brand', '')}"))
            if not evidence:
                story.append(para('未在检索摘要中找到明确金额，需手动核对或补充手动参考价。'))
            for item in evidence[:4]:
                if not isinstance(item, dict):
                    continue
                story.append(para('价格证据：' + str(item.get('price', '')) + '｜' + str(item.get('snippet', ''))))
                source_url = str(item.get('url', ''))
                if source_url:
                    story.append(Paragraph('<link href="' + escape(source_url, quote=True) + '" color="blue">来源：' + escape(str(item.get('title', '价格来源'))) + '</link>', style))
                else:
                    story.append(para('来源：' + str(item.get('title', '客户填写')) + '（未外部核验）'))
        market = comparison.get('market_reference') if isinstance(comparison, dict) else []
        if isinstance(market, list) and market:
            story.append(para('行业市场参考（不等于 A/B 官方报价）'))
            for item in market[:4]:
                if isinstance(item, dict):
                    story.append(para(str(item.get('price', '')) + '｜' + str(item.get('snippet', ''))))
        if isinstance(comparison, dict) and comparison.get('notice'):
            story.append(para(comparison['notice']))
        story.append(para('优先使用用户确认信息和下方带来源的公开资料；没有来源的报价、折扣、竞品价格和优惠必须标为待核实。'))
        story.append(para('可准备的角度：费用构成、总成本、适用方案、可验证案例、付款条件和下一步确认。'))
        story.append(para('本资料不会自动推荐降价，也不能把公开检索摘要当成客户预算或竞品报价。'))
        story.append(Paragraph('三、公开检索资料', heading))
    else:
        story.append(Paragraph('二、公开检索资料', heading))

    if body.background.digest_version:
        if body.background.overview:
            story.append(para('机构背景｜' + body.background.overview.title))
            story.append(para(body.background.overview.summary))
            story.append(Paragraph('<link href="' + escape(str(body.background.overview.url), quote=True) + '" color="blue">查看机构背景来源</link>', style))
        elif body.background.basic_background:
            story.append(para(body.background.basic_background))
        if not body.background.insights:
            story.append(para('暂无可靠的整合结果，请查看下方核实说明。'))
        for i, item in enumerate(body.background.insights, 1):
            story.append(para(f'{i}. {item.title}'))
            story.append(para(item.summary))

            for source in item.sources:
                label = source.title + '｜' + (source.date or '日期未提供')
                story.append(Paragraph('<link href="' + escape(str(source.url), quote=True) + '" color="blue">' + escape(label) + '</link>', style))
            story.append(Spacer(1, 8))
    else:
        rows = ([body.background.overview] if body.background.overview else []) + body.background.sources
        if not rows: story.append(para('暂无匹配资料。以下文件仅包含用户提供的信息，不代表检索已成功。'))
        for i, row in enumerate(rows, 1):
            story.append(para(f'{i}. {row.topic or "背景概况"}｜{row.title}'))
            story.append(para(row.summary))
            story.append(para(f'来源：{row.publisher or urlsplit(str(row.url)).hostname}｜发布日期：{row.date or "未提供"}'))
            story.append(Paragraph('<link href="' + escape(str(row.url), quote=True) + '" color="blue">查看来源原文</link>', style))
            story.append(Spacer(1,8))
    for gap in body.background.gaps:
        if any(word in gap for word in ('失败', '超时', '重试', '未完成', '不可用')):
            story.append(para(gap))
    story.append(para('信息可能不准确或存在时效差异，请仔细甄别，并以来源原文及机构最新公布的信息为准。'))
    def footer(canvas, document):
        canvas.setFont(font,9); canvas.drawRightString(A4[0]-42,22,f'第 {document.page} 页')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
