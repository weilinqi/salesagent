"""Identity-aware customer language shared by greetings and ongoing dialogue."""

def audience(persona):
    persona = persona or {}
    title = str(persona.get('title', ''))
    context = str(persona.get('scenario_context', ''))
    # Personal purchasing takes precedence over a person's employer or profession.
    if any(x in title + context for x in ('自用', '个人购买', '给自己', '给孩子', '给父母')):
        return 'personal'
    if any(x in title for x in ('家长', '老人', '老年', '退休', '学生', '个人', '消费者', '宝妈')):
        return 'personal'
    if any(x in title for x in ('采购', '经理', '工程师', '负责人', '主管', '总监', '技术人员', '专业人员', '企业客户')):
        return 'professional'
    return 'neutral'


def opening(persona=None):
    if audience(persona) == 'professional':
        return '你好，请介绍一下产品的适用场景和主要特点。'
    return '你好，请简单介绍一下这款产品或服务，我想了解是否适合。'


def dialogue_rules(persona):
    mode = audience(persona)
    register = {
        'personal': '当前是个人购买场景。用清楚、自然、礼貌的日常表达；不要使用项目选型、供应商评审、立项、采购流程等企业话术。不得凭空加入公司、团队或同事。',
        'professional': '当前身份具有专业背景。仅在岗位和本次购买场景相关时使用专业术语，不堆砌术语，不虚构项目、预算或采购权限。',
        'neutral': '身份或购买场景尚不明确时使用中性、易懂的表达，不默认对方是企业采购人员。',
    }[mode]
    return ('【身份与逐轮对话规则：优先于通用性格话术】\n' + register +
        '\n每轮结合对象身份、已知需求、销售最新回答及完整对话上下文生成回复，不复用固定问答模板。'
        '\n已回答清楚的问题不重复追问；解释清楚后自然推进，回答含糊时针对遗漏追问，前后矛盾时提出具体质疑。'
        '\n态度随沟通质量逐渐变化，不无故同意购买或突然拒绝。每轮通常只推进一个相关问题，句式和长度按内容变化。'
        '\n保持自然、得体、简洁，避免过度口语、刻意语气词和机械重复。老人、家长等身份不等于缺乏知识；不模仿年龄、方言，不推断收入、能力、疾病或家庭状况。'
        '\n用户提供的身份和沟通偏好优先；关联学校或公司不等于职业采购。需求未知时用询问确认，不编造为既定事实。')
