"""Compare explicit same-currency pricing/discount/ad scenarios, never execute them."""
from datetime import datetime, timezone
from operations_analysis import unit_economics, number, money, UNIT_FIELDS
from research import canonical, digest
from decimal import Decimal


def compare(data):
    if not isinstance(data, dict) or set(data) != {'base', 'target_contribution', 'plans', 'inventory_state'}:
        raise ValueError('invalid_campaign_input')
    base = data['base']
    if not isinstance(base, dict) or set(base) - set(UNIT_FIELDS): raise ValueError('invalid_campaign_base')
    # Each plan has an explicit ad cost; the base ad-rate is not charged again.
    cost_base = {**base, 'ad_rate': 0}
    calculated = unit_economics(cost_base)
    if calculated['status'] == 'HOLD': return dict(status='HOLD', missing=calculated['missing'], plans=[], marketplace_writes=False)
    target = money(number(data['target_contribution'], 'target_contribution'))
    inventory = data['inventory_state']
    if inventory not in ('unknown', 'sufficient', 'tight', 'overstock'): raise ValueError('invalid_inventory_state')
    plans = data['plans']
    if not isinstance(plans, list) or not 1 <= len(plans) <= 10: raise ValueError('invalid_campaign_plans')
    results = []
    for plan in plans:
        if not isinstance(plan, dict) or set(plan) != {'name', 'price', 'merchant_discount', 'ad_cost_per_unit', 'affiliate_rate'}:
            raise ValueError('invalid_campaign_plan')
        name = plan['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80: raise ValueError('invalid_campaign_name')
        price = money(number(plan['price'], 'price', minimum=Decimal('.01')))
        discount = money(number(plan['merchant_discount'], 'merchant_discount'))
        net = price - discount
        if net < Decimal('.01'): raise ValueError('discount_exceeds_price')
        ads = money(number(plan['ad_cost_per_unit'], 'ad_cost_per_unit'))
        affiliate = money(net * number(plan['affiliate_rate'], 'affiliate_rate', maximum=1))
        economics = unit_economics({**cost_base, 'price': float(net)})
        pre_ad = money(Decimal(str(economics['contribution'])) - affiliate)
        contribution = money(pre_ad - ads)
        budget = money(pre_ad - target)
        if contribution < 0: recommendation = '预计单件贡献为负，先调整成本、折扣或投放'
        elif contribution < target: recommendation = '低于目标单件贡献，需调整方案'
        elif inventory == 'tight': recommendation = '贡献达到目标，但库存紧张，优先补货并收缩促销扩量'
        elif inventory == 'unknown': recommendation = '贡献达到目标，库存与履约能力尚待核实'
        elif inventory == 'overstock': recommendation = '可作为积压商品的待审促销方案，需核实增量需求'
        else: recommendation = '可列入小范围测试，按实际广告归因和退货数据复核'
        results.append(dict(name=name, sale_price=float(price), merchant_discount=float(discount), net_revenue=float(net),
                            affiliate_cost=float(affiliate), ad_cost_per_unit=float(ads),
                            total_cost=float(money(Decimal(str(economics['total_cost'])) + affiliate + ads)),
                            contribution=float(contribution), pre_ad_contribution=float(pre_ad),
                            target_contribution=float(target), ad_allowance_at_target=float(budget),
                            target_possible_before_ads=budget >= 0, meets_target=contribution >= target,
                            recommendation=recommendation, cost_breakdown=economics['cost_breakdown']))
    evidence = dict(input=data, input_sha256=digest(canonical(data)), model_version='campaign-contribution-v1',
                    calculated_at=datetime.now(timezone.utc).isoformat(), verification='caller_input_not_independently_verified')
    result = dict(status='CALCULATED', currency=base['currency'], plans=results, evidence=evidence, marketplace_writes=False,
                  assumptions=['按优惠后商家收入计费，所有成本同币种。', '只扣商家承担的优惠，平台补贴不重复扣减。',
                               '广告为每单分摊金额；基础表广告比例不再计入。达人佣金按优惠后收入计算。',
                               '简化贡献模型，不包括未输入的税费和固定成本；广告增量效果和库存状态需核实。'])
    result['sha256'] = digest(canonical(result))
    return result
