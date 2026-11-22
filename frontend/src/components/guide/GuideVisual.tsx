interface GuideVisualProps {
  type: 'practice' | 'customers'
}

function Callout({ number, title, text }: { number: number; title: string; text: string }) {
  return (
    <div className="flex gap-2 rounded-lg border border-blue-100 bg-blue-50/70 p-2.5 text-xs text-blue-950">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-600 font-bold text-white">{number}</span>
      <p><span className="font-semibold">{title}：</span>{text}</p>
    </div>
  )
}

function PracticeVisual() {
  return (
    <div className="space-y-3 rounded-xl border border-gray-200 bg-slate-50 p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-900">价格异议处理准备示例</p>
          <p className="text-xs text-gray-500">价格模式会先准备 A/B 比较，再生成资料和气泡</p>
        </div>
        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-700">示例示意</span>
      </div>

      <div className="grid gap-2 rounded-lg border border-gray-200 bg-white p-3 text-xs sm:grid-cols-2">
        <div><span className="text-gray-500">比较的产品或班型</span><p className="mt-1 font-medium text-gray-900">高三数学一对一</p></div>
        <div><span className="text-gray-500">客户身份 / 职务</span><p className="mt-1 font-medium text-gray-900">高三学生家长</p></div>
        <div><span className="text-gray-500">客户所属机构</span><p className="mt-1 font-medium text-gray-900">石家庄某重点中学</p></div>
        <div><span className="text-gray-500">本次练习目标</span><p className="mt-1 font-medium text-gray-900">确认价格顾虑并争取试听</p></div>
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-white px-2 py-1 font-medium text-amber-900">A｜学而思</span>
          <span className="text-amber-700">对比</span>
          <span className="rounded bg-white px-2 py-1 font-medium text-amber-900">B｜新东方</span>
          <span className="text-gray-600">价格比较方面：单课时价格</span>
        </div>
        <p className="mt-2 text-gray-700">客户顾虑：客户认为学而思单课时价格比新东方贵，担心多出的费用不值得。</p>
        <p className="mt-1 text-[11px] text-amber-800">A/B 和具体顾虑未填完整时，“开始对练”按钮会保持禁用但不会消失。</p>
      </div>

      <div className="grid gap-2 lg:grid-cols-2">
        <div className="rounded-lg border border-emerald-200 bg-white p-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-emerald-800">自动背景调查</p>
            <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">自动触发</span>
          </div>
          <p className="mt-2 text-xs text-gray-600">价格模式会分别检索 A、B 和市场参考；找不到明确金额时保留用户填写内容，不自动编造。</p>
          <p className="mt-2 text-[11px] text-blue-600 underline">查看来源原文</p>
        </div>
        <div className="rounded-lg border border-primary/20 bg-white p-3">
          <p className="text-xs font-semibold text-gray-900">销售准备 PDF</p>
          <div className="mt-2 flex gap-2">
            <span className="rounded bg-primary px-2 py-1 text-[11px] font-medium text-white">展示 PDF</span>
            <span className="rounded border border-primary/30 px-2 py-1 text-[11px] font-medium text-primary">下载 PDF</span>
          </div>
          <p className="mt-2 text-[11px] text-gray-500">修改情景后需要重新生成。</p>
        </div>
      </div>

      <div className="rounded-lg border border-blue-200 bg-blue-50/40 p-3">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-blue-900">这个场景，可以怎么聊</p>
          <span className="rounded-full border border-blue-200 bg-white px-2 py-0.5 text-[10px] text-blue-700">更多角度</span>
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {['先问清哪部分贵', '确认预算范围', '拆解费用构成', '推进下一步'].map((text, index) => (
            <div key={text} className={`rounded-xl rounded-bl-sm border border-blue-100 bg-white px-3 py-2 text-xs text-gray-700 ${index > 1 ? 'opacity-65' : ''}`}>
              {text}
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Callout number={1} title="历史填写" text="复用以前的客户和情景配置。" />
        <Callout number={2} title="价格检索" text="A/B/C 和市场参考分开检索，证据和来源一起展示。" />
        <Callout number={3} title="PDF" text="先展示再下载，修改后重新生成。" />
        <Callout number={4} title="更多角度" text="替换为另一组沟通思路。" />
      </div>
    </div>
  )
}

function CustomersVisual() {
  return (
    <div className="space-y-3 rounded-xl border border-gray-200 bg-slate-50 p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-900">客户管理关键交互示例</p>
          <p className="text-xs text-gray-500">重点不在普通表单，而在于识别、确认和批量操作</p>
        </div>
        <span className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white">上传表格</span>
      </div>
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div className="grid grid-cols-5 bg-gray-100 px-3 py-2 text-[11px] font-semibold text-gray-600">
          <span>客户</span><span>电话</span><span>状态</span><span>待确认内容</span><span>操作</span>
        </div>
        <div className="grid grid-cols-5 border-t border-gray-100 px-3 py-2 text-xs">
          <span>张三</span><span>138****5678</span><span>跟进中</span><span className="rounded bg-amber-100 px-1.5 py-1 text-amber-900">预算待确认</span><span className="text-red-600">删除</span>
        </div>
        <div className="grid grid-cols-5 border-t border-gray-100 px-3 py-2 text-xs">
          <span>李四</span><span>139****4321</span><span>已报价</span><span className="text-gray-400">—</span><span className="text-red-600">删除</span>
        </div>
      </div>
      <div className="rounded-lg border-2 border-red-300 bg-white/70 p-3">
        <p className="text-xs font-semibold text-red-800">批量删除模式</p>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-gray-700">
          <span className="flex h-10 w-10 items-center justify-center rounded-md border-2 border-red-400 bg-white/50 font-bold text-red-600">✓</span>
          <span>只有点击“批量删除”后才显示大号勾选框</span>
          <span className="ml-auto rounded bg-red-600 px-2 py-1 font-medium text-white">删除选中（1）</span>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <Callout number={1} title="黄色内容" text="必须人工确认，确认后恢复普通颜色。" />
        <Callout number={2} title="批量确认" text="一次处理整张表所有黄色内容。" />
        <Callout number={3} title="批量删除" text="进入模式后才出现勾选框。" />
      </div>
    </div>
  )
}

export default function GuideVisual({ type }: GuideVisualProps) {
  return type === 'practice' ? <PracticeVisual /> : <CustomersVisual />
}
