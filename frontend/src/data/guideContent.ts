export interface GuideControl {
  label: string
  description: string
}

export interface GuideSection {
  id: string
  title: string
  path?: string
  icon: string
  summary: string
  highlights: string[]
  workflow: string[]
  controls: GuideControl[]
  visual?: 'practice' | 'customers'
  adminOnly?: boolean
}

export const GUIDE_SECTIONS: GuideSection[] = [
  {
    id: 'navigation',
    title: '顶部导航',
    icon: '🧭',
    summary: '在销售智能体的各个板块之间切换，并管理通知、账户和登录状态。',
    highlights: ['板块切换', '当前页面高亮', '通知提醒', '账户菜单与退出'],
    workflow: ['点击板块名称进入对应页面', '点击铃铛查看通知', '通过头像确认当前账号', '使用退出结束登录'],
    controls: [
      { label: 'Logo / 销售智能体', description: '点击返回仪表盘。' },
      { label: '板块导航', description: '在仪表盘、对练、客户管理、SPIN准备、行业简报、知识库、历史、画像和设置之间切换。' },
      { label: '当前板块高亮', description: '蓝色背景表示当前所在页面。' },
      { label: '通知铃铛', description: '查看报告、简报和系统提醒。' },
      { label: '用户头像', description: '显示当前登录账号。' },
      { label: '退出登录', description: '结束当前登录并返回登录页。' },
      { label: '手机端菜单', description: '窗口变窄时打开折叠导航。' },
    ],
  },
  {
    id: 'dashboard',
    title: '仪表盘',
    path: '/dashboard',
    icon: '📊',
    summary: '查看练习数据、进步趋势、最近活动和常用功能入口。',
    highlights: ['练习次数与总时长', '平均得分和进步幅度', '本周进度与连续练习', '最近活动', '快捷操作', '总体使用说明'],
    workflow: ['查看统计卡片', '检查本周进度', '从最近活动继续复盘', '通过快捷操作进入常用功能'],
    controls: [
      { label: '练习次数', description: '累计练习会话数量。' },
      { label: '总时长', description: '有效练习的累计时长。' },
      { label: '平均得分', description: '根据训练评价计算的平均得分。' },
      { label: '进步幅度', description: '比较近期与前一阶段的得分变化。' },
      { label: '本周进度', description: '显示本周练习次数、时长和得分。' },
      { label: '连续练习天数', description: '统计连续使用系统的天数。' },
      { label: '最近活动', description: '打开最近的对练、对话或复盘。' },
      { label: '开始练习', description: '进入对练配置页面。' },
      { label: '快捷操作', description: '集中打开练习、简报、历史、画像、设置和使用说明。' },
      { label: '使用说明', description: '随时打开总体说明中心。' },
    ],
  },
  {
    id: 'practice',
    title: '对练',
    path: '/practice',
    icon: '🎙️',
    summary: '选择训练模式、准备情景、与AI客户实时对话，并获得阶段总结和最终复盘；价格模式会额外围绕 A/B 价格比较准备资料。',
    highlights: ['完整销售对练、拒绝挽回与价格异议处理', '价格模式要求 A/B 品牌和具体顾虑', 'A/B/C 与市场参考分别检索', '价格证据表、PDF和多角度话术', '价格顾虑为主线，比较作为辅助', '文字与语音实时对练及最终复盘'],
    workflow: ['选择训练模式', '填写具体情景并点击整理信息', '价格模式核对 A/B 品牌、比较产品或班型、价格比较方面和具体顾虑', '检查价格证据表、PDF和话术气泡', '进入实时对练', '生成阶段总结和最终报告'],
    controls: [
      { label: '完整销售对练', description: '从开场到推进下一步，练习完整销售流程。' },
      { label: '拒绝挽回', description: '从客户拒绝开始，练习回应异议和争取后续机会。' },
      { label: '价格异议处理', description: '从客户提出价格顾虑开始，练习问清和什么相比、拆解价值并推进下一步。' },
      { label: '初步介绍与整理信息', description: '用一段自然描述填写情景，点击整理后由AI拆分客户身份、机构、品牌、产品和价格顾虑。' },
      { label: '客户身份／职务', description: '价格模式第一项必填，说明对话对象是谁。' },
      { label: '客户所属机构／关联人物', description: '填写客户所在学校、公司或关联人物；它不等同于 A/B/C 品牌。' },
      { label: 'A/B/C 品牌', description: 'A是我方品牌，B是主要对比品牌，C是可选的其他对比品牌；A和B必须不同。' },
      { label: '比较的产品或班型', description: '填写双方实际比较的课程或产品，例如高三数学一对一。' },
      { label: '价格比较方面', description: '说明比较的是单课时价格、课程总价、年费或课时包等哪一方面。' },
      { label: '客户的具体价格顾虑', description: '写清客户认为哪家贵、担心什么；只要非空即可，不再限制字数。' },
      { label: '开始对练', description: '按钮始终显示；必填项不完整时禁用，补齐后自动启用。' },
      { label: '开始准备', description: '进入当前模式的客户与情景配置。' },
      { label: '历史填写', description: '复用以前填写过的客户和练习配置。' },
      { label: '返回选择模块', description: '放弃当前配置并重新选择训练模式。' },
      { label: '调整模拟角色风格', description: '设置客户级别、性格、决策风格和声线。' },
      { label: '声线预览', description: '试听并选择AI客户的声音。' },
      { label: '自动背景调查', description: '价格模式会分别检索 A、B、C 和市场参考，而不是只搜索一个通用产品。' },
      { label: '价格资料分别检索', description: '显示 A/B/C 各自来源数量；搜索超时会保留已填写的比较信息。' },
      { label: '价格证据表', description: '只收录检索摘要中明确出现的金额和原文片段，并保留来源；没有明确金额不会自动编造。' },
      { label: '重新检索', description: '联网搜索超时或不可用时重新发起 A/B/C 和市场检索。' },
      { label: '展示PDF', description: '生成包含对象信息、价格比较和证据来源的销售准备资料并在页面内预览。' },
      { label: '下载PDF', description: '保存已经生成并展示的准备资料。' },
      { label: '这个场景，可以怎么聊', description: '价格模式会生成围绕价格顾虑和 A/B 比较的气泡；AI未返回时先显示本地可用角度。' },
      { label: '更多角度', description: '在保留当前角度的基础上，继续生成不同表达和推进方式。' },
      { label: '重新生成', description: '背景、PDF或话术失败时重新请求。' },
      { label: '直接进入对练', description: '价格模式必填信息完成后开始；如果仍有缺失，按钮会显示但保持禁用。' },
      { label: '重新开始', description: '清除当前准备状态并重新配置。' },
      { label: '进入对练', description: '进入实时对话页面。' },
      { label: '按住说话', description: '按住麦克风录音，松开后发送语音。' },
      { label: '发送', description: '发送文字消息。' },
      { label: '停止播放', description: '打断正在播放的AI语音。' },
      { label: '暂停 / 继续语音', description: '控制历史语音的播放状态。' },
      { label: '生成阶段总结', description: '分析当前阶段并生成得分、问题和建议。' },
      { label: '资料面板', description: '查看对话前PDF、价格证据、知识库片段和查询历史。' },
      { label: '价格对话规则', description: '价格顾虑是主线，比较只用于解释价格差异，不要求每轮都重复 A/B 对比。' },
      { label: '实时价格异议指导', description: '优先提示价格原因、预算差距和价值确认，不直接建议降价或编造优惠。' },
      { label: '打开原始PDF', description: '查看知识来源的完整PDF。' },
      { label: '下载原件', description: '下载知识库或准备资料PDF。' },
      { label: '删除资料历史', description: '删除不需要的资料查询记录。' },
      { label: '导出PDF', description: '保存最终评价报告。' },
    ],
    visual: 'practice',
  },  {
    id: 'customers',
    title: '客户管理',
    path: '/customers',
    icon: '👥',
    summary: '上传任意格式的客户表格，由AI整理为可编辑网页表格，并集中处理待确认内容。',
    highlights: ['上传Excel并自动识别表头', '黄色待确认内容', '批量确认黄色', '批量删除模式', '编辑、新增列和删除表格'],
    workflow: ['上传客户表格', '检查AI识别的表头', '处理黄色待确认内容', '编辑或补充客户信息', '按需批量删除记录'],
    controls: [
      { label: '上传表格', description: '上传.xlsx、.xlsm或.csv，页面顶部始终可用。' },
      { label: '已导入表格', description: '点击切换历史导入的不同表格。' },
      { label: 'AI自动识别', description: '识别人工表头、电话、日期、金额等列类型。' },
      { label: '单元格编辑', description: '点击单元格修改，回车或失焦保存。' },
      { label: '搜索', description: '搜索当前表格中的任意内容。' },
      { label: '新增记录', description: '在表格末尾增加一行。' },
      { label: '新增列', description: '为当前表格添加新列。' },
      { label: '修改列名', description: '点击表头修改网页显示名称。' },
      { label: '删除单条记录', description: '删除当前行客户记录。' },
      { label: '黄色待确认内容', description: '表示格式异常或AI极其不确定，需要人工检查。' },
      { label: '无表头待确认列', description: '在最右侧集中显示当前行的黄色内容。' },
      { label: '单项确认', description: '只确认当前一项黄色内容。' },
      { label: '确认本行全部内容', description: '一次确认当前行所有黄色内容。' },
      { label: '批量确认黄色', description: '确认整张表全部黄色内容，不删除原始数据。' },
      { label: '批量删除', description: '进入删除模式，表格左侧才显示大号勾选框。' },
      { label: '全选当前页', description: '选择或取消选择当前页全部记录。' },
      { label: '删除选中', description: '删除当前页勾选的客户记录。' },
      { label: '取消 / 退出批量删除', description: '清除选择并隐藏勾选框。' },
      { label: '删除整张表', description: '删除当前完整客户表格。' },
      { label: '分页', description: '切换上一页或下一页。' },
    ],
    visual: 'customers',
  },
  {
    id: 'spin',
    title: 'SPIN准备',
    path: '/spin/preparation',
    icon: '🧠',
    summary: '调查客户背景、确认痛点并生成针对性的SPIN问题，再转入对练。',
    highlights: ['AI客户调研', '确认背景和痛点', '生成S/P/I/N问题', '直接转入对练'],
    workflow: ['输入客户名称', '查看AI调研', '确认背景和痛点', '生成SPIN问题', '开始对练'],
    controls: [
      { label: '客户名称', description: '输入公司或个人名称开始调查。' },
      { label: 'AI调查', description: '检索客户基本信息、动态和潜在痛点。' },
      { label: '补充信息', description: '手动填写或修正行业和规模。' },
      { label: '调研结果', description: '查看客户背景、媒体报道、融资、高管和近期动态。' },
      { label: '确认信息', description: '确认调研结果并进入痛点选择。' },
      { label: '痛点标签', description: '选择成本、效率、客户流失等已知痛点。' },
      { label: '自定义痛点', description: '补充列表外的客户问题。' },
      { label: '确认痛点并生成问题', description: '根据客户背景生成SPIN问题。' },
      { label: 'S/P/I/N问题清单', description: '分别查看现状、问题、影响和价值问题。' },
      { label: '重新生成', description: '当前问题不合适时重新生成。' },
      { label: '开始对练', description: '携带客户背景和问题进入对练。' },
    ],
  },
  {
    id: 'briefs',
    title: '行业简报',
    path: '/briefs',
    icon: '📰',
    summary: '查看行业新闻摘要，并设置每日自动推送。',
    highlights: ['今日与历史简报', '行业和关键词订阅', '手动刷新', '一次性生成简报'],
    workflow: ['选择订阅行业', '填写可选关键词', '保存订阅或立即刷新', '打开简报核对原文'],
    controls: [
      { label: '立即刷新', description: '手动抓取最新行业新闻。' },
      { label: '今日', description: '查看今天生成的简报。' },
      { label: '历史', description: '查看以前生成的简报。' },
      { label: '我的订阅', description: '管理行业和关键词订阅。' },
      { label: '行业选择', description: '勾选需要每日推送的行业。' },
      { label: '关键词', description: '缩小新闻范围并提高匹配精度。' },
      { label: '保存订阅', description: '保存后每日自动生成并推送。' },
      { label: '一次性生成', description: '不订阅，只为指定行业生成一次。' },
      { label: '打开简报', description: '查看新闻摘要、重点和原始来源。' },
      { label: '删除', description: '删除不需要的历史简报。' },
      { label: '来源分级与核对', description: '查看L1-L4来源等级，并打开原文核实AI摘要。' },
    ],
  },
  {
    id: 'knowledge',
    title: '知识库',
    path: '/knowledge',
    icon: '📚',
    summary: '检索内部销售资料、上传PDF文档，并基于知识库生成SPIN问题。',
    highlights: ['内部与联网检索', '上传和管理PDF', '文档处理状态', '基于知识库生成SPIN问题'],
    workflow: ['选择检索范围', '输入关键词搜索', '按需上传PDF', '查看文档处理状态', '生成SPIN问题'],
    controls: [
      { label: '知识检索', description: '切换到内部知识和联网检索页面。' },
      { label: '文档管理', description: '上传PDF并查看处理状态。' },
      { label: 'SPIN问题生成', description: '根据客户背景和知识库生成问题。' },
      { label: '检索范围', description: '选择本地优先、仅内部或仅联网。' },
      { label: '搜索', description: '按关键词或完整问题检索知识。' },
      { label: '网络补充资料', description: '查看公开网页摘要并打开原文核对。' },
      { label: '重试', description: '搜索失败后重新请求。' },
      { label: '刷新状态', description: '更新文档处理进度。' },
      { label: '同步原始数据', description: '将后端知识目录中的资料加入处理队列。' },
      { label: '上传PDF', description: '上传同事提供的原始PDF并选择分类。' },
      { label: '上传并入库', description: '解析PDF并生成可检索知识片段。' },
      { label: '文档状态', description: '查看等待、处理中、完成或失败。' },
      { label: '知识库统计', description: '查看文档数、知识片段数和分类数。' },
      { label: '生成SPIN问题', description: '根据行业、规模和痛点生成问题。' },
      { label: '使用的知识库内容', description: '查看生成时引用的资料。' },
    ],
  },
  {
    id: 'history',
    title: '历史',
    path: '/history',
    icon: '🕘',
    summary: '查看历史练习记录、得分、时长和复盘报告。',
    highlights: ['近30天统计', '场景与日期筛选', '继续未完成对话', '查看复盘'],
    workflow: ['查看统计', '选择场景和日期范围', '打开会话', '继续对话或查看复盘'],
    controls: [
      { label: '练习次数', description: '近30天的练习数量。' },
      { label: '平均得分', description: '近30天的平均评分。' },
      { label: '练习时长', description: '近30天累计练习时间。' },
      { label: '已完成', description: '近30天已完成会话数量。' },
      { label: '类型筛选', description: '按陌拜电话、线上会议、工厂参观或商务宴请筛选。' },
      { label: '日期筛选', description: '选择7天、30天、90天或全部。' },
      { label: '继续', description: '恢复尚未结束的对话。' },
      { label: '查看对话', description: '打开已完成的历史对话。' },
      { label: '查看', description: '进入评分和复盘报告。' },
      { label: '分页', description: '查看更多历史记录。' },
    ],
  },
  {
    id: 'profile',
    title: '画像',
    path: '/profile',
    icon: '🧑‍💼',
    summary: '查看个人资料、能力雷达图、自我评估和最近活动。',
    highlights: ['编辑个人资料', '六维能力雷达图', '自动能力评分', '最近练习活动'],
    workflow: ['查看个人资料', '检查能力雷达图', '查看自我评估', '从最近活动打开复盘'],
    controls: [
      { label: '编辑资料', description: '修改姓名和个人简介。' },
      { label: '总练习次数', description: '累计练习数量。' },
      { label: '练习时长', description: '累计练习时间。' },
      { label: '最强项', description: '当前平均得分最高的能力。' },
      { label: '待提升', description: '当前平均得分较低的能力。' },
      { label: '能力雷达图', description: '查看六项销售能力的综合表现。' },
      { label: '自我评估', description: '查看各能力分数和进度条。' },
      { label: '最近活动', description: '打开最近练习记录或复盘。' },
      { label: '保存', description: '保存个人资料修改。' },
    ],
  },
  {
    id: 'settings',
    title: '设置',
    path: '/settings',
    icon: '⚙️',
    summary: '管理账号、安全、通知、AI行为和外观。',
    highlights: ['账号与密码', '通知偏好', 'AI客户行为', '外观主题', '危险操作'],
    workflow: ['选择左侧设置分类', '修改对应内容', '点击保存设置', '危险操作需谨慎确认'],
    controls: [
      { label: '账号设置', description: '查看邮箱、用户名并修改密码。' },
      { label: '保存修改', description: '保存账号资料和密码修改。' },
      { label: '通知偏好', description: '设置邮件摘要、周报、练习提醒和系统通知。' },
      { label: 'AI行为', description: '设置响应速度、人格风格、提示级别和自动阶段总结。' },
      { label: '保存设置', description: '保存当前分类下的设置。' },
      { label: '外观主题', description: '选择浅色、深色或跟随系统。' },
      { label: '注销账号', description: '永久删除账号和全部数据，不可恢复。' },
    ],
  },
]

export const MODULE_PATH_MAP: Record<string, string> = {
  '/practice': 'practice',
  '/customers': 'customers',
  '/spin/preparation': 'spin',
  '/briefs': 'briefs',
  '/knowledge': 'knowledge',
  '/history': 'history',
  '/profile': 'profile',
  '/settings': 'settings',
}

export function isAiConversationPath(pathname: string): boolean {
  return pathname.startsWith('/practice/chat')
}

export function sectionForPath(pathname: string): GuideSection | null {
  if (pathname.startsWith('/practice')) return GUIDE_SECTIONS.find(section => section.id === 'practice') || null
  if (pathname.startsWith('/customers')) return GUIDE_SECTIONS.find(section => section.id === 'customers') || null
  if (pathname.startsWith('/spin')) return GUIDE_SECTIONS.find(section => section.id === 'spin') || null
  if (pathname.startsWith('/briefs')) return GUIDE_SECTIONS.find(section => section.id === 'briefs') || null
  if (pathname.startsWith('/knowledge')) return GUIDE_SECTIONS.find(section => section.id === 'knowledge') || null
  if (pathname.startsWith('/history')) return GUIDE_SECTIONS.find(section => section.id === 'history') || null
  if (pathname.startsWith('/profile')) return GUIDE_SECTIONS.find(section => section.id === 'profile') || null
  if (pathname.startsWith('/settings')) return GUIDE_SECTIONS.find(section => section.id === 'settings') || null
  return null
}
