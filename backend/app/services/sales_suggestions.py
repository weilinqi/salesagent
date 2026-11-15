"""Short role-appropriate sales angles; no analysis or invented benefits."""
from app.services.research_digest import ask_json
from app.services.sales_material import MaterialRequest, MaterialBackground
from pydantic import BaseModel, Field
from typing import Literal

class PreviousSuggestion(BaseModel):
    title: str = Field(max_length=30)
    speech: str = Field(max_length=180)

class SuggestionRequest(MaterialRequest):
    training_mode: Literal['full', 'rejection'] = 'full'
    background: MaterialBackground = Field(default_factory=MaterialBackground)
    previous: list[PreviousSuggestion] = Field(default_factory=list, max_length=30)

async def sales_suggestions(body):
    previous = [item.model_dump() for item in getattr(body, 'previous', [])]
    mode_rules = ('当前训练模块是拒绝挽回，即使用户未提拒绝，也按客户已拒绝的销售情景提供不同应对角度。'
                  '结合产品和身份自然生成，不假定或透露本轮具体拒绝原因，不为用户编造已发生的对话；不要生成普通寒暄开场。'
                  if getattr(body, 'training_mode', 'full') == 'rejection' else '')
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
            for item in body.background.insights]}, timeout=20)
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
