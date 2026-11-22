"""Short role-appropriate sales angles; no analysis or invented benefits."""
from app.services.research_digest import ask_json
from app.services.sales_material import MaterialRequest, MaterialBackground
from pydantic import BaseModel, Field
from typing import Literal

class PreviousSuggestion(BaseModel):
    title: str = Field(max_length=30)
    speech: str = Field(max_length=180)

class SuggestionRequest(MaterialRequest):
    training_mode: Literal['full', 'rejection', 'price_objection'] = 'full'
    background: MaterialBackground = Field(default_factory=MaterialBackground)
    previous: list[PreviousSuggestion] = Field(default_factory=list, max_length=30)


def fallback_suggestions(body):
    """Keep the practice preparation usable when the model is slow or unavailable."""
    profile = body.profile
    mode = getattr(body, 'training_mode', 'full')
    if mode == 'price_objection':
        brand_a = profile.price_brand_a or '当前方案'
        brand_b = profile.price_brand_b or '对比方案'
        aspect = profile.price_comparison_aspect or '价格'
        return [
            {'title': '先问清比较对象', 'speech': f'您说{brand_a}比{brand_b}贵，主要是{aspect}上的差距，还是课程内容也不一样？'},
            {'title': '确认最在意的结果', 'speech': '除了价格，您最希望孩子在这门课里得到什么结果？'},
            {'title': '拆开看费用', 'speech': f'如果把{aspect}和包含的服务分开看，您最想先确认哪一部分？'},
            {'title': '了解预算范围', 'speech': '方便说说您目前大概希望把预算控制在什么范围吗？'},
            {'title': '推进下一步', 'speech': '如果我把价格和包含内容逐项说明，您愿意再比较一次吗？'},
        ]
    if mode == 'rejection':
        return [
            {'title': '先接住顾虑', 'speech': '我理解您现在暂时不考虑，您最担心的是哪一方面？'},
            {'title': '确认原因', 'speech': '是预算、效果还是之前的体验让您有顾虑？'},
            {'title': '不急着成交', 'speech': '今天不急着做决定，我只想先确认您真正担心的问题。'},
            {'title': '留一个下一步', 'speech': '如果我补充一份更有针对性的资料，您愿意再看看吗？'},
        ]
    product = profile.product or '这个方案'
    return [
        {'title': '了解当前情况', 'speech': f'您现在对{product}最想先了解哪一方面？'},
        {'title': '确认目标', 'speech': f'您希望这次使用{product}后，最重要的变化是什么？'},
        {'title': '了解顾虑', 'speech': '目前还有哪些因素会让您犹豫？'},
        {'title': '推进下一步', 'speech': '如果我把关键信息说明清楚，您愿意继续了解吗？'},
    ]

async def sales_suggestions(body):
    previous = [item.model_dump() for item in getattr(body, 'previous', [])]
    mode = getattr(body, 'training_mode', 'full')
    if mode == 'rejection':
        mode_rules = ('当前训练模块是拒绝挽回，即使用户未提拒绝，也按客户已拒绝的销售情景提供不同应对角度。'
                      '结合产品和身份自然生成，不假定或透露本轮具体拒绝原因，不为用户编造已发生的对话；不要生成普通寒暄开场。')
    elif mode == 'price_objection':
        mode_rules = ('当前训练模块是价格异议处理。每个角度都必须服务于识别或回应价格顾虑，可围绕客户和什么相比、预算差距、价值拆解、总成本、风险、付款条件和下一步确认展开。'
                      '如果 profile 中提供了 price_brand_a、price_brand_b、price_brand_c、price_comparison_aspect 和 price_concern，话术必须直接围绕这些品牌与同一个价格比较方面展开；不要更换比较对象，也不要把单课时价格和总价混为一谈。'
                      '话术使用“价格比较方面”“按课时计算”“总费用”等自然说法，不要使用生硬术语。'
                      '不要直接建议打折，不要编造报价、竞品价格、优惠、预算或客户事实；资料不足时用询问和核对表达。'
                      '话术要让客户愿意继续说清顾虑，而不是只重复“我们很值”。')
    else:
        mode_rules = ''
    data = await ask_json(
        mode_rules +
        '你是销售练习助手。根据用户确认的产品、客户身份、需求、目标和检索概括，给出约5个不同角度的参考话术。'
        '返回 {"items":[{"title":"简短角度标题","speech":"一句可直接对客户说的话"}]}。最多5条，少于5条也可以，不凑数。'
        '只要标题和话术，不要分析说明。面向老人、家长用自然尊重的日常表达，企业专业人员可适度使用业务术语。'
        '紧扣具体产品及客户需求，不重复追问已知信息，不套用通用模板。'
        '不捏造功能、优惠、试听政策、承诺或客户事实；资料不足以确认的内容用了解需求、询问或核对表达。'
        'previous是之前展示过的角度与话术，本轮换不同角度，不只是同义改写。'
        '检索概括不是已验证的产品承诺，不以第三方介绍为依据作保证。不同条目避免重复。',
        {'previous': previous, 'profile': body.profile.model_dump(), 'background': [
            {'title': item.title, 'summary': item.summary, 'caveat': item.caveat}
            for item in body.background.insights]}, timeout=12)
    items, seen = [], {item['speech'] for item in previous}
    for item in data.get('items', []):
        if not isinstance(item, dict): continue
        title, speech = item.get('title'), item.get('speech')
        if not isinstance(title, str) or not isinstance(speech, str): continue
        title, speech = title.strip(), speech.strip()
        if not title or not speech or len(title)>30 or len(speech)>180 or speech in seen: continue
        seen.add(speech)
        items.append({'title': title, 'speech': speech})
        if len(items)==5: break
    if not items: raise ValueError('No valid suggestions')
    return {'items': items}
