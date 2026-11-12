"""Targeted public search and bounded, source-linked sales preparation PDFs."""
import asyncio
import io
import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, HttpUrl
from app.services.preparation import PreparationProfile, LABELS, lookup_overview
from app.services.search import search_via_mcp, SearchUnavailable
from app.services.research_digest import identify_roles, make_plans, summarize

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

class MaterialRequest(BaseModel):
    profile: PreparationProfile
    background: MaterialBackground

def search_key(organization, product, needs, target):
    return '\n'.join(x.strip() for x in (organization, product, needs, target))

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

async def research(organization='', product='', needs='', target=''):
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
    sources, gaps, seen = [], [], set()
    grades = set(re.findall(r'高[一二三]|初[一二三]|[一二三四五六]年级', target + needs))
    for plan, rows in zip(plans, outcomes):
        found = 0
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict): continue
            title, summary = str(row.get('title','')), str(row.get('snippet',''))
            corpus = title + ' ' + summary
            if plan[0] == '通用课程参考' and not any(t in corpus for t in ('课程标准', '教学大纲', '学习目标', '教育部', '教育委员会')): continue
            if plan[0] == '机构背景' and not any(t in corpus for t in ('简介', '概况', '成立', '主营', '培养', '示范', '重点')): continue
            url = row.get('url') or row.get('link') or ''
            parts = urlsplit(url) if isinstance(url, str) else None
            if not parts or parts.scheme not in ('https','http') or not parts.hostname or not summary: continue
            # Exact supplied entity/product name; never accept a partial same-name match.
            if plan[2].casefold() not in corpus.casefold(): continue
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
            if found >= (3 if len(plans) > 3 else 4): break
        if not found:
            gaps.append(plan[0] + ('：' + rows if isinstance(rows, str) else '：暂无同时匹配关键词的公开资料。'))
    if any(s in product for s in ('数学','英语','语文','物理','化学','生物')):
        gaps.append('课程难度需核对课程或试题原文；不能根据学校名气或检索摘要推断。')
    insights = await summarize(roles, sources[:12])
    if sources and not insights:
        gaps.append('已检索到资料，但暂未完成可靠概括，请重试；未将零散摘要充作整理结果。')
    return dict(organization=roles.get('customer') or organization, overview=overview,
        roles=roles, insights=insights, digest_version=1, sources=sources[:12], gaps=list(dict.fromkeys(gaps))[:10],
        checked_at=datetime.now(timezone.utc).isoformat(), search_key=search_key(organization,product,needs,target),
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
    for key, value in body.profile.model_dump().items():
        story.append(para(LABELS[key] + '：' + (value or '未填写')))
    story.append(Paragraph('二、公开检索资料', heading))
    story.append(para(body.background.notice))
    if body.background.digest_version:
        if not body.background.insights:
            story.append(para('暂无可靠的整合结果，请查看下方核实说明。'))
        for i, item in enumerate(body.background.insights, 1):
            story.append(para(f'{i}. {item.title}'))
            story.append(para(item.summary))
            if item.caveat:
                story.append(para('说明：' + item.caveat))
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
    story.append(Paragraph('三、信息缺口与核实说明', heading))
    for gap in body.background.gaps or ['请核对来源原文及适用时间，摘要不作为效果承诺。']:
        story.append(para(gap))
    def footer(canvas, document):
        canvas.setFont(font,9); canvas.drawRightString(A4[0]-42,22,f'第 {document.page} 页')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
