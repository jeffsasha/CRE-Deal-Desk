"""Fill the Simplified Chinese catalog. Run after `makemessages -l zh_Hans`:
    .venv/bin/python locale/fill_zh.py && .venv/bin/python manage.py compilemessages -l zh_Hans
Untranslated strings fall back to English automatically."""
import sys
from pathlib import Path

import polib

ZH = {
    "Dashboard": "仪表盘", "Properties": "物业", "Deals": "交易", "Calendar & Deadlines": "日历与期限",
    "Tasks & Checklists": "任务与清单", "Documents": "文件", "Contacts & Companies": "联系人与公司",
    "Commissions": "佣金", "Reports": "报表", "Settings": "设置",
    "Title": "产权", "Survey": "测量", "Property insurance": "财产保险", "Financing": "融资", "Inspections": "检查",
    "All": "全部", "Sales & acquisitions": "买卖", "Leases": "租赁", "Business assets": "生意转让",
    "Lead": "潜在客户", "Evaluating": "评估中", "Touring": "看房中", "LOI": "意向书", "Negotiating": "谈判中",
    "Under Contract": "已签合同", "Due Diligence": "尽职调查", "Preparing to Close": "准备交割", "Closed": "已成交",
    "On Hold": "暂停", "Terminated": "已终止", "Lost": "已流失", "Archived": "已归档",
    "Administrator": "管理员", "Broker": "经纪人", "Coordinator": "协调员", "Read-only": "只读",
    "today": "今天", "tomorrow": "明天", "yesterday": "昨天",
    "in %(n)d day": "%(n)d 天后", "%(n)d day ago": "%(n)d 天前",
    "Contacts": "联系人",
    "Sale / purchase": "买卖", "Lease": "租赁", "Business": "生意转让",
    "Buyer": "买方", "Seller": "卖方", "Both sides": "双方", "Tenant": "租户", "Landlord": "业主（出租方）",
    "Buying a business": "收购生意", "Selling a business": "出售生意",
    "New lease": "新租约", "Renewal": "续租", "Expansion": "扩租", "Assignment": "转租 / 租约转让",
    "Buyer (our client)": "买方（我方客户）", "Seller (our client)": "卖方（我方客户）",
    "Tenant (our client)": "租户（我方客户）", "Landlord (our client)": "业主（我方客户）",
    "Business owner / seller (our client)": "生意业主 / 卖方（我方客户）",
    "Existing property": "已有物业", "New property": "新物业", "No property yet": "暂无物业",
    "Street address": "街道地址", "City": "城市", "Property type": "物业类型", "Suite": "单元号",
    "Responsible broker": "负责经纪人", "Stage": "阶段", "Deal name": "交易名称",
    "Optional — generated from the property and deal type.": "可选——将根据物业和交易类型自动生成。",
    "Choose who we represent for this kind of deal.": "请选择我方在此类交易中代表的一方。",
    "Choose the property.": "请选择物业。", "Enter the street address.": "请输入街道地址。",
    "Without a property, give the deal a name.": "没有物业时，请为交易命名。",
    "Purchase / acquisition": "购买 / 收购", "Sale / listing disposition": "出售 / 挂牌出售",
    "Land acquisition": "土地收购", "Land sale": "土地出售", "Commercial lease": "商业租赁",
    "Lease renewal": "续租", "Lease expansion": "扩租", "Lease assignment": "租约转让",
    "Business asset sale": "生意资产转让",
    "All active": "全部进行中", "All inactive": "全部非进行中", "Blocked by another party": "被其他方阻滞",
    "Closing within 30 days": "30 天内交割", "Closing within 90 days": "90 天内交割",
    "Deal %(id)s created.": "已创建交易 %(id)s。",
    "Demo mode — fictional sample data in an isolated database. Nothing here is SKW transaction history.":
        "演示模式——独立数据库中的虚构示例数据，并非 SKW 的真实交易记录。",
    "SKW DealDesk home": "SKW DealDesk 首页", "Main": "主菜单", "Sign out": "退出登录", "Menu": "菜单",
    "Search and commands": "搜索与命令", "Search or jump to…": "搜索或跳转…", "Switch theme": "切换主题",
    "Notifications": "通知", "Search everything for": "全局搜索", "No matches": "无匹配结果", "Navigate": "导航",
    "Search": "搜索", "Search deals, properties, contacts, documents — or type a command": "搜索交易、物业、联系人、文件——或输入命令",
    "move": "移动", "open": "打开", "close": "关闭",
    "New deal": "新建交易", "Create": "新建", "Upload document": "上传文件", "New contact": "新建联系人",
    "Deal board": "交易看板", "Go to": "前往", "Deadline calendar": "期限日历",
    "Extractions awaiting review": "待审核的合同提取", "Deposits awaiting confirmation": "待确认的保证金",
    "Issues": "问题", "Switch to light theme": "切换到浅色主题", "Appearance": "外观",
    "Switch to dark theme": "切换到深色主题", "Match system theme": "跟随系统主题",
    "Today": "今日", "What needs attention, what could delay a deal, and what documents or money are still missing.":
        "需要关注的事项、可能延误交易的风险，以及仍缺失的文件或款项。",
    "Overdue": "已逾期", "Due today": "今日到期", "Next 7 days": "未来 7 天", "Next 30 days": "未来 30 天",
    "No date until the actual event is recorded": "在记录实际发生日期之前不计算日期",
    "Awaiting trigger": "等待触发", "Needs review": "需审核", "Overdue tasks": "逾期任务",
    "Extractions to review": "待审核提取", "Deal progress": "交易进度",
    "Where every open deal stands on the path to closing": "每笔进行中交易距离交割的进度",
    "On hold": "暂停", "step %(n)s of %(total)s": "第 %(n)s / %(total)s 步", "Blocked": "受阻",
    "Some deadlines are awaiting a trigger or need review": "部分期限正在等待触发或需要审核",
    "Dates pending": "日期待定", "Next:": "下一项：", "No dated deadline": "暂无已定日期的期限",
    "Checklist items approved, waived or not applicable": "已批准、豁免或不适用的清单项目",
    "%(pct)s%% checklist": "清单完成 %(pct)s%%", "No open deals of this type.": "暂无此类进行中的交易。",
    "No open deals.": "暂无进行中的交易。", "Create a deal": "新建交易",
    "Calendar": "日历", "Due": "到期", "Deadline": "期限", "Deal": "交易", "Responsible": "负责人", "Basis": "依据",
    "Internal": "内部", "Rule confirmed": "规则已确认", "Rule unconfirmed": "规则未确认",
    "No computed deadlines in the next 7 days.": "未来 7 天没有已计算的期限。",
    "Unresolved diligence items": "未完成的尽调事项",
    "“Received” stays open until reviewed and approved": "“已收到”在审核并批准前仍视为未完成",
    "Feasibility periods ending (14 days)": "即将结束的可行性期（14 天内）", "None in the next 14 days.": "未来 14 天内没有。",
    "Expiration dates do not by themselves determine earnest money refundability.": "到期日本身并不能决定保证金是否可退还。",
    "Upcoming closings (30 days)": "即将交割（30 天内）", "contract": "合同", "internal target": "内部目标",
    "No closings in the next 30 days.": "未来 30 天没有交割。",
    "Deposits due or awaiting receipt confirmation": "待支付或待确认收款的保证金",
    "Deals blocked by another party": "被其他方阻滞的交易", "Reminder delivery failures": "提醒发送失败",
    "Volume": "成交量", "Month": "月", "Quarter": "季度", "Year": "年",
    "Closed sales volume": "已成交销售额", "by actual closing date": "按实际交割日期",
    "%(n)s deal": "%(n)s 笔交易", "Executed leases": "已签租约", "separate from sales volume": "不计入销售额",
    "%(n)s lease": "%(n)s 份租约", "lease consideration": "租约总额",
    "Expected on active deals": "进行中交易的预期佣金", "Earned (by earned date)": "已赚取（按赚取日期）",
    "Cash received by SKW": "SKW 实收现金", "Designated broker's actual receipts": "指定经纪人实收金额",
    "Unpaid receivables (today)": "未收应收款（截至今日）", "Unpaid distributions (today)": "未付分配款（截至今日）",
    "Totals are computed from the commission ledger. “+ N unknown” means records whose amount is not known; they are not counted as zero.":
        "合计由佣金账簿计算。“+ N 未知”表示金额未知的记录，不按零计算。",
    "Deals by stage": "按阶段查看交易",
    "Drag a card to change its stage. Closing is done from the deal's Closing tab.": "拖动卡片即可更改阶段。交割请在交易的“交割”标签页完成。",
    "Read-only view.": "只读视图。", "Filter…": "筛选…", "Table": "表格", "Board": "看板", "Closing": "交割",
    "SKW represents": "SKW 代表", "Representation not recorded": "未记录代理关系",
    "Reason (required for Terminated/Lost)": "原因（终止/流失时必填）", "Change stage": "更改阶段",
    "Upload": "上传", "Edit": "编辑", "Lease consideration": "租约总额", "Executed contract price": "合同成交价",
    "Not approved": "未批准", "Effective date": "生效日期", "Not confirmed": "未确认",
    "Contract closing date": "合同交割日期", "Internal target": "内部目标日期", "Actual closing": "实际交割",
    "Next action": "下一步", "Sales, acquisitions, leases, renewals, assignments and business asset transactions.":
        "出售、收购、租赁、续租、转租及生意资产交易。",
    "Deposits": "保证金", "Three quick choices. Everything else can be added on the deal page.": "三个快速选择，其他信息可稍后在交易页面补充。",
    "What kind of deal?": "交易类型？", "Buying or selling real estate, including land": "买卖房地产（含土地）",
    "New lease, renewal, expansion or assignment": "新租约、续租、扩租或租约转让",
    "Buying or selling an operating business": "收购或出售经营中的生意",
    "Who do we represent?": "我方代表哪一方？", "Dual representation — both sides": "双边代理——同时代表双方",
    "SKW represents this side": "SKW 代表此方", "Lease type": "租约类型", "Deal details": "交易信息",
    "Property": "物业", "Choose property": "选择物业", "Client": "客户",
    "A company or person. Matched to an existing company when the name is the same.": "公司或个人。名称相同时会匹配已有公司。",
    "Other client": "另一方客户", "Create deal": "创建交易", "Cancel": "取消", "Back": "返回", "Save": "保存",
    "Remove this record? The removal is recorded in the activity log.": "确定删除此记录？删除操作会记入活动日志。",
    "Remove": "删除", "Search…": "搜索…", "all": "全部", "Apply": "应用", "Clear": "清除",
    "%(n)s record": "%(n)s 条记录", "Saved views": "已保存视图", "Columns": "列", "Show columns": "显示列",
    "Save view": "保存视图", "Name": "名称", "Save current filters": "保存当前筛选", "Export CSV": "导出 CSV",
    "No records match.": "没有匹配的记录。", "Previous": "上一页", "Page %(p)s of %(t)s": "第 %(p)s / %(t)s 页",
    "Next": "下一页", "Sign in": "登录", "Demo mode — fictional sample data in an isolated database.": "演示模式——独立数据库中的虚构示例数据。",
    "Sign in to DealDesk": "登录 DealDesk", "private workspace": "私有工作区",
    "The username or password is incorrect.": "用户名或密码不正确。", "Username": "用户名", "Password": "密码",
    "ID": "编号", "Type": "类型", "Priority": "优先级", "Blocked by": "阻滞方", "Price / consideration": "价格 / 总额",
    "Updated": "更新时间", "Overview": "概览", "Parties": "各方", "Contract & Dates": "合同与日期", "Checklist": "清单",
    "Activity": "动态",
}

sys.path.insert(0, str(Path(__file__).parent))
for _mod in ("zh_extra_1", "zh_extra_2", "zh_extra_3", "zh_extra_4", "zh_extra_5"):
    ZH.update(__import__(_mod).ZH)

po_path = Path(__file__).parent / "zh_Hans" / "LC_MESSAGES" / "django.po"
po = polib.pofile(str(po_path))
po.metadata["Language"] = "zh_Hans"
po.metadata["Plural-Forms"] = "nplurals=1; plural=0;"
missing = []
for e in po:
    zh = ZH.get(e.msgid)
    if zh is None:
        missing.append(e.msgid)
        continue
    if e.msgid_plural:
        e.msgstr_plural = {0: zh}
    else:
        e.msgstr = zh
    if "fuzzy" in e.flags:
        e.flags.remove("fuzzy")
po.save(str(po_path))
print(f"translated {len(po) - len(missing)} / {len(po)}")
if missing:
    print("missing:", missing)
    sys.exit(1)
