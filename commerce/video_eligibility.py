"""Current automatic video policy; explicit media requests use their own gates.

The existing performance reports have a free-form source reference. Product
fulfillment snapshots and store-wide analytics cannot verify an exact-SKU paid
or fulfilled non-cancelled sale. Keep that adapter gap explicit in every default
plan/review, rather than accepting a caller-provided `verified` flag as evidence.
"""


def automatic_video_policy(observations):
    return {'strategy': 'verified_product_sales_before_video', 'status': 'deferred',
        'automatic_generation_allowed': False, 'explicit_human_requests_unchanged': True,
        'sale_verification': 'verified_product_sales_adapter_missing',
        'reason': '默认先完成商品图片与上架验证；同商品真实销量补证后再评估展示、使用或UGC风格视频。当前报告和发货单不能自动解锁视频生产。',
        'missing_sales_contract': ['同平台、店铺、市场与准确SKU的销售来源及版本',
            '已付款或已履约且未取消的真实交易状态与数量；退货/退款另记',
            '统计窗口、采集时间、来源完整性及新鲜度核验'],
        'subsequent_gates': ['当前商品与素材权利', '视频制作预算及执行授权', '成片质量与发布审核'],
        'observations': observations}
