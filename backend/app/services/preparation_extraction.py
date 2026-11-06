"""Tolerant structured extraction and conservative local recovery."""
import json
import re

ALIASES = {
    'industry': ['industry', '推销行业', '行业'],
    'product': ['product', '产品或服务', '推销产品', '产品'],
    'target': ['target', '对象身份／职务', '对象身份/职务', '推销对象', '对象'],
    'organization': ['organization', '关联公司／机构', '公司', '机构', '学校'],
    'needs': ['needs', '需求与使用场景', '对象需求', '需求'],
    'preferences': ['preferences', '喜好与顾虑', '喜好', '顾虑'],
    'goal': ['goal', '本次练习目标', '练习目标', '目标'],
}

def parse_extraction(raw):
    if not isinstance(raw, str):
        raise ValueError('Invalid model output')
    text = re.sub(r'<think>.*?</think>', '', raw, flags=re.S | re.I)
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{', text):
        try:
            data, _ = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        for wrapper in ('profile', 'data', 'information'):
            if isinstance(data.get(wrapper), dict):
                data = data[wrapper]
                break
        result = {}
        for key, aliases in ALIASES.items():
            for alias in aliases:
                if alias not in data:
                    continue
                value = data[alias]
                if isinstance(value, list):
                    value = '；'.join(item for item in value if isinstance(item, str))
                if value is None:
                    value = ''
                if isinstance(value, str):
                    result[key] = value.strip()[:1000]
                    break
        if result:
            return result
    raise ValueError('No structured fields')

def extract_explicit_information(message):
    """Only recover explicit labelled values and narrow sales sentence patterns."""
    result = {}
    clauses = re.split(r'[,，;；。\n]+', message)
    for clause in clauses:
        clause = clause.strip()
        for key, aliases in ALIASES.items():
            for alias in aliases:
                match = re.match(re.escape(alias) + r'\s*[:：]\s*(.+)$', clause)
                if match:
                    result[key] = match[1].strip()[:1000]
        product = re.match(r'^(?:我(?:想|要|准备)?|我们(?:想|要|准备)?)?(?:推销|销售|介绍)(?!对象)(?:的产品是|的是)?\s*(.+)$', clause)
        if product:
            result.setdefault('product', product[1].strip())
        target = re.match(r'^(?:推销对象|销售对象|对象|客户)(?:是|为)\s*(.+)$', clause)
        if target:
            value = target[1]
            school = re.match(r'就读于(.+?(?:学校|中学|小学|大学))的(.+)$', value)
            if school:
                result.setdefault('organization', school[1])
                value = school[2]
            result.setdefault('target', value)
        need = re.match(r'^(?:家长|客户|对方)(?:想让|希望|需要|想要)(.+)$', clause)
        if need:
            result.setdefault('needs', need[1].strip())
    if re.search(r'(数学|英语|语文|物理|化学).*(课|辅导)', result.get('product', '')):
        result.setdefault('industry', '教育培训')
    return {key: value[:1000] for key, value in result.items()}
