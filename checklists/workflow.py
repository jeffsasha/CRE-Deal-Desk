"""Small transaction checklists; definitions are read-only until a user saves a task."""
from django.db import transaction
from django.utils.translation import get_language

from core.permissions import has_perm
from .models import ChecklistItem
from .services import update_item


STAGES = {
    "contract": ("Contract effective", "合同生效"),
    "diligence": ("Due diligence", "尽职调查"),
    "prepare": ("Before closing", "交割准备"),
    "finish": ("Closing & follow-through", "交割与收尾"),
    "application": ("Application & information", "资料与申请"),
    "review": ("Review & approval", "核实与批准"),
    "agreement": ("Terms & signing", "条款与签约"),
    "payments": ("Payments", "付款"),
    "delivery": ("Delivery & occupancy", "交付与使用"),
    "commission": ("Commission & follow-through", "佣金与收尾"),
}
COPY = {
    "title": ("Deal checklist", "交易清单"), "close": ("Collapse", "收起"),
    "saved": ("Saved", "已保存"), "saving": ("Saving…", "保存中…"),
    "error": ("Not saved. Please try again.", "未保存，请重试。"),
    "retry": ("Retry", "重试"),
    "read_only": ("View only", "仅查看"),
    "unknown": ("Represented side not recorded", "尚未记录 SKW 代表方"),
    "help": ("Autosaves", "自动保存"),
}

# Compact display labels; keep the original descriptions and saved task keys.
SHORT_LABELS = {
    'effective': ('Effective Date', '合同生效'), 'em': ('EM', 'EM'),
    'consideration': ('Independent Consideration', '独立对价'),
    'escrow': ('Title / Escrow', 'Title / Escrow'),
    'title': ('Title Commitment', 'Title Commitment'),
    'title-review': ('Title exceptions', '产权例外'),
    'survey': ('Survey', 'Survey'), 'survey-review': ('Survey review', 'Survey 审核'),
    'inspection': ('Inspection', '物业检查'), 'environmental': ('Environmental', '环境调查'),
    'income': ('Rent roll / Estoppels', 'Rent roll / Estoppels'),
    'land-use': ('Land use / Floodplain', '用途 / 洪水区'),
    'access': ('Utilities / Access', '配套 / 通行权'),
    'financing': ('Financing / Appraisal', '融资 / 估价'),
    'objections': ('Title / Survey objections', '产权 / Survey 异议'),
    'decision': ('Proceed / Extend / Terminate', '继续 / 延期 / 终止'),
    'extension': ('Extension', '延期文件'), 'cda': ('CDA', 'CDA'),
    'buyer-rebate': ('Buyer rebate', '买方 Rebate'), 'seller-rebate': ('Seller rebate', '卖方 Rebate'),
    'statement': ('Closing Statement', 'Closing Statement'), 'closing': ('Closing', '交割'),
    'commission-paid': ('Commission received', '佣金到账'),
    'final-documents': ('Final docs', '最终文件'),
    'assets': ('Assets / Financials', '资产 / 财务资料'),
    'business-review': ('Business due diligence', '生意尽调'),
    'lease-transfer': ('Lease transfer', '租约承接'),
    'operations': ('Business info', '运营资料'), 'financials': ('P&L', 'P&L'),
    'business-plan': ('Business plan / Funding', '计划 / 资金'),
    'identity': ('ID / Guarantor ID', '驾照 / 身份证明'),
    'screening-consent': ('Screening consent', '调查授权'),
    'screening': ('Background / Credit', '背景 / 信用调查'),
    'approval': ('Landlord approval', '房东批准'),
    'renewal-terms': ('Renewal terms', '续约条款'), 'updated-information': ('Updated info', '资料更新'),
    'expansion': ('Area / Plans / Use', '面积 / 图纸 / 用途'),
    'assignment-information': ('Assignee info', '受让方资料'),
    'landlord-consent': ('Landlord consent', '房东同意'),
    'liability': ('Assignment obligations', '转让责任'),
    'loi': ('LOI', 'LOI'), 'economics': ('Rent / NNN / TI', '租金 / NNN / TI'),
    'signed': ('Signed lease', '租约签署'), 'guaranty': ('Guaranty', '担保'),
    'dates': ('Key dates', '关键日期'), 'deposit': ('Security deposit', '押金'),
    'first-rent': ("First month's rent", '首月租金'),
    'rent-transfer': ('Rent allocation', '租金划分'), 'rent-change': ('Adjusted rent', '租金调整'),
    'prorata': ('Pro-rata rent', 'Pro-rata 租金'), 'other-payment': ('Other charges', '其他款项'),
    'coi': ('COI', 'COI'), 'handover': ('Handover / Keys', '交付 / 钥匙'),
    'utilities': ('Utilities', 'Utilities'), 'ti': ('TI / Inspections', '装修 / 验收'),
    'co-requirement': ('CO requirements', 'CO 要求'), 'co': ('CO', 'CO'),
    'permits': ('Permits', '经营许可'), 'rebate': ('Rebate', 'Rebate'),
    'invoice': ('Commission invoice', '佣金发票'),
}


def text(pair):
    return pair[1] if (get_language() or "en").startswith("zh") else pair[0]


def catalog(deal):
    lease = deal.is_lease
    sides = set(deal.representations.filter(is_skw=True).values_list("side", flat=True))
    first, second = ("tenant", "landlord") if lease else ("buyer", "seller")
    role = "both" if {first, second} <= sides else first if first in sides else second if second in sides else "unknown"
    prefix = deal.transaction_type.replace("_", "-") + "-" + role + "-"
    rows = []

    def add(stage, key, en, zh, optional=False, financial=False):
        label = SHORT_LABELS[key]
        if key == 'signed':
            label = {'lease': ('Signed lease', '租约签署'), 'lease_renewal': ('Signed renewal', '续约签署'),
                     'lease_expansion': ('Signed expansion', '扩租签署'), 'lease_assignment': ('Signed assignment', '转让协议签署')}[deal.transaction_type]
        elif key == 'deposit' and deal.transaction_type in {'lease_renewal', 'lease_expansion'}:
            label = ('Deposit adjustment', '押金补差')
        elif key == 'deposit' and deal.transaction_type == 'lease_assignment':
            label = ('Deposit transfer', '押金转交')
        elif key == 'escrow' and deal.is_business_asset:
            label = ('Closing contact', '交割对接')
        elif key == 'final-documents' and not deal.is_business_asset:
            label = ('Title Policy / Final docs', 'Title Policy / 最终文件')
        rows.append({"key": prefix + key, "stage": stage, "en": en, "title": text(label),
                     "description": text((en, zh)), "optional": optional, "financial": financial})

    if lease:
        action = {"tenant": ("submitted", "已提交"), "landlord": ("received and reviewed", "已收到并审阅"),
                  "both": ("submitted and review confirmed", "已提交并确认审阅"), "unknown": ("confirmed", "已确认")}[role]
        payment = {"tenant": ("paid", "已支付"), "landlord": ("received", "已确认收取"),
                   "both": ("paid and received", "已支付并确认收取"), "unknown": ("payment confirmed", "付款状态已确认")}[role]
        kind = deal.transaction_type
        if kind == "lease":
            for key, en, zh, optional in [
                ("operations", "Tenant business / operating information", "租客公司及运营资料", False),
                ("financials", "P&L / financial information", "P&L／财务资料", True),
                ("business-plan", "New business plan / funding information", "新业务计划／资金情况", True),
                ("identity", "Tenant / guarantor identification", "租客／担保人身份证明", True),
            ]:
                add("application", key, en + " " + action[0], zh + action[1], optional)
            add("application", "screening-consent", "Background / credit check authorization confirmed", "背景／信用调查授权已确认", True)
            add("application", "screening", "Background / credit check completed and feedback confirmed", "背景／信用调查已完成并反馈", True)
            add("application", "approval", "Landlord approval confirmed", "房东批准已确认")
        elif kind == "lease_renewal":
            add("review", "renewal-terms", "Renewal terms and notice dates confirmed", "续约条款和通知期限已确认")
            add("review", "updated-information", "Updated tenant information " + action[0], "更新后的租客资料" + action[1], True)
        elif kind == "lease_expansion":
            add("review", "expansion", "Expansion area, plans and business use confirmed", "扩租面积、图纸和用途已确认")
            add("review", "updated-information", "Expansion financial / operating information " + action[0], "扩租财务／运营资料" + action[1], True)
        else:
            add("review", "assignment-information", "Assignee financial / operating information " + action[0], "受让方财务／运营资料" + action[1])
            add("review", "landlord-consent", "Landlord consent to assignment confirmed", "房东对租约转让的同意已确认")
            add("review", "liability", "Assignor / assignee and guarantor obligations confirmed", "转让方、受让方和担保人责任已确认")

        if kind == "lease":
            add("agreement", "loi", "LOI / commercial terms confirmed", "LOI／主要商务条款已确认")
        add("agreement", "economics", "Use, rent, NNN/CAM, free rent and TI terms confirmed", "用途、租金、NNN/CAM、免租及 TI 条款已确认")
        agreement = {"lease": ("Lease fully signed", "Lease 已签署完成"), "lease_renewal": ("Renewal agreement fully signed", "续约协议已签署完成"),
                     "lease_expansion": ("Expansion amendment fully signed", "扩租协议已签署完成"), "lease_assignment": ("Assignment agreement fully signed", "转让协议已签署完成")}[kind]
        add("agreement", "signed", *agreement)
        add("agreement", "guaranty", "Guaranty signed / updated", "担保文件已签署／更新", True)
        add("agreement", "dates", "Effective, delivery and rent commencement dates confirmed", "生效、交付和起租日期已确认")
        if kind == "lease":
            add("payments", "deposit", "Security deposit " + payment[0], "押金" + payment[1])
            add("payments", "first-rent", "First month's rent " + payment[0], "首月租金" + payment[1])
        elif kind == "lease_assignment":
            add("payments", "deposit", "Security deposit transfer / replacement confirmed", "押金转交／替换安排已确认")
            add("payments", "rent-transfer", "Rent and outstanding balances allocated", "租金及未结余额划分已确认")
        else:
            add("payments", "deposit", "Additional security deposit " + payment[0], "押金补差" + payment[1], True)
            add("payments", "rent-change", "Adjusted rent payment confirmed", "调整后的租金付款已确认")
        if kind in {"lease", "lease_expansion"}:
            add("payments", "prorata", "Pro-rata rent confirmed", "Pro-rata 租金安排已核实", True)
        if kind == "lease":
            add("payments", "other-payment", "Other initial charges confirmed", "其他首期款项已核实", True)
        add("delivery", "coi", "Insurance / COI confirmed", "保险／COI 已确认", True)
        if kind != "lease_renewal":
            add("delivery", "handover", "Premises, keys and handover completed", "场地、钥匙及交接已完成")
            add("delivery", "utilities", "Utilities arranged", "Utilities 已安排", True)
            add("delivery", "ti", "TI / construction and required inspections completed", "TI／施工及相关检查已完成", True)
        if kind != "lease_renewal":
            add("delivery", "co-requirement", "CO applicability and responsible party confirmed", "CO 适用性与办理责任已核实")
            add("delivery", "co", "Required CO obtained / existing CO confirmed applicable", "所需 CO 已取得／现有 CO 适用已确认", True)
            add("delivery", "permits", "Required business / operating permits confirmed", "所需行业／经营许可已确认", True)
        add("commission", "cda", "Commission agreement / payment instructions confirmed", "佣金协议／付款指示已确认（CDA 如适用）", financial=True)
        add("commission", "rebate", "Rebate arrangement and required consents confirmed", "Rebate 安排及所需同意已确认", True, True)
        add("commission", "invoice", "Commission invoice / payment request sent", "佣金发票／付款请求已发送", True, True)
        add("commission", "commission-paid", "SKW commission received", "SKW 佣金已到账", financial=True)
    else:
        business = deal.is_business_asset
        add("contract", "effective", "Signed contract and Effective Date confirmed", "签署合同及 Effective Date 已确认")
        add("contract", "em", "Earnest Money paid", "Earnest Money 已支付", business)
        if not business:
            add("contract", "consideration", "Independent Consideration paid", "Independent Consideration 已支付", True)
        add("contract", "escrow", "Closing / escrow contact confirmed" if business else "Title / escrow contact confirmed", "交割／escrow 联系信息已确认" if business else "Title／escrow 联系信息已确认", business)
        if business:
            add("diligence", "assets", "Business asset list and financial information reviewed", "生意资产清单及财务资料已审阅")
            add("diligence", "business-review", "Business due diligence completed", "生意尽职调查已完成")
            add("diligence", "lease-transfer", "Lease transfer and landlord consent confirmed", "租约承接及房东同意已确认", True)
            add("diligence", "permits", "Business licenses / permit transfer confirmed", "经营许可／许可证转移已确认", True)
        else:
            title_action = ("delivered to buyer", "已交付买方") if role == "seller" else ("received", "已收到")
            add("diligence", "title", "Title Commitment " + title_action[0], "Title Commitment " + title_action[1])
            add("diligence", "title-review", "Title Commitment / exceptions reviewed", "Title Commitment／例外事项已审阅")
            add("diligence", "survey", "Survey " + title_action[0], "Survey " + title_action[1])
            add("diligence", "survey-review", "Survey reviewed and title / lender acceptance confirmed", "Survey 已审阅，title／适用 lender 接受情况已确认")
            if not deal.transaction_type.startswith("land_"):
                add("diligence", "inspection", "Property inspection completed", "物业检查已完成", True)
            add("diligence", "environmental", "Environmental due diligence completed", "环境调查已完成", True)
            if not deal.transaction_type.startswith("land_"):
                add("diligence", "income", "Leases, rent roll and estoppels reviewed", "租约、rent roll 和 estoppel 已核实", True)
            if deal.transaction_type.startswith("land_"):
                add("diligence", "land-use", "Land use, restrictions and floodplain reviewed", "土地用途、限制及洪水区已核实")
                add("diligence", "access", "Utilities / access and easements confirmed", "Utilities／通行权及地役权已核实")
        if deal.financing_status != "not_applicable":
            add("diligence", "financing", "Financing / appraisal confirmed", "融资／appraisal 已确认", True)
        if not business:
            add("prepare", "objections", "Title / survey objections resolved", "Title／Survey objections 已处理", True)
        add("prepare", "decision", "Client decision to proceed, extend or terminate confirmed", "继续、延期或终止的客户决定已确认")
        if deal.extensions.exists():
            add("prepare", "extension", "Extension signed", "延期文件已签署", True)
        add("prepare", "cda", "CDA confirmed", "CDA 已确认", financial=True)
        add("prepare", "buyer-rebate", "Buyer rebate, amount and required consents confirmed", "Buyer Rebate、金额及所需同意已确认", True, True)
        add("prepare", "seller-rebate", "Seller rebate, amount and required consents confirmed", "Seller Rebate、金额及所需同意已确认", True, True)
        add("prepare", "statement", "Closing Statement reviewed", "Closing Statement 已核对")
        add("finish", "closing", "Signing, closing funds and closing completion confirmed", "签署、交割资金及交割完成已确认")
        add("finish", "commission-paid", "SKW commission received", "SKW 佣金已到账", financial=True)
        add("finish", "final-documents", "Final documents followed through" if business else "Final documents / Title Policy followed through", "最终文件已跟进" if business else "最终文件／Title Policy 已跟进", True)
    return role, rows


def build(deal, user):
    role, definitions = catalog(deal)
    saved = {item.workflow_key: item for item in deal.checklist_items.exclude(workflow_key="")}
    stages = {}
    for row in definitions:
        if row["financial"] and not has_perm(user, "commission.view"):
            continue
        item = saved.get(row["key"])
        # Keep earlier skip decisions in storage, without a disabled row or a new N/A control.
        if item and item.status == "not_applicable":
            continue
        row.update(status=item.status if item else "not_started", done=bool(item and item.status in {"approved", "waived"}), na=bool(item and item.status == "not_applicable"))
        stage = stages.setdefault(row["stage"], {"key": row["stage"], "title": text(STAGES[row["stage"]]), "items": []})
        stage["items"].append(row)
    for stage in stages.values():
        stage["done"] = sum(row["done"] for row in stage["items"] if not row["na"])
        stage["total"] = sum(not row["na"] for row in stage["items"])
    labels = {"tenant": ("Tenant Rep", "租客代表"), "landlord": ("Landlord Rep", "房东代表"), "buyer": ("Buyer Rep", "买方代表"), "seller": ("Seller Rep", "卖方代表"), "both": ("Both sides", "双方代表")}
    return {"role": role, "role_label": text(labels[role]) if role in labels else text(COPY["unknown"]), "stages": list(stages.values()),
            "done": sum(stage["done"] for stage in stages.values()), "total": sum(stage["total"] for stage in stages.values()),
            "text": {key: text(value) for key, value in COPY.items()}}


@transaction.atomic
def save_task(deal, definition, state, actor):
    status = {"done": "approved", "todo": "not_started", "na": "not_applicable"}[state]
    item, _created = ChecklistItem.objects.select_for_update().get_or_create(
        deal=deal, workflow_key=definition["key"], defaults={"title": definition["en"], "category": STAGES[definition["stage"]][0], "workflow_financial": definition["financial"]})
    if item.status == status:
        return item
    old_status = item.status
    item.status = status
    item.not_applicable_reason = "Marked not applicable in deal checklist." if state == "na" else ""
    if state != "done":
        item.approved_on = None
        item.reviewed_on = None
    return update_item(item, actor, old_status)
