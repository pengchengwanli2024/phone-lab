# 外部电商项目的学习与接入判断

2026-11-17 复核。前两个 Sealeap 项目是此前已参考的来源；后三个是本轮首次静态复核，未安装、未运行、未连接账号或付费采集。目录、许可证及源码观察不等于生产能力验收。

| 项目 | 当前项目关系 | 值得消化 | 接入判断 |
| --- | --- | --- | --- |
| [Sealeap Amazon](https://github.com/xjli360/sealeap-amazon-skills) | 已有固定版本与受限适配；当前HEAD未变化 | 商品/广告/现金/评论/竞品的输入输出合同、离线校验 | 继续转化实际需要的少量能力，不重复导入或把所有SOP算成执行器 |
| [Sealeap Ecommerce](https://github.com/xjli360/sealeap-ecommerce-skills) | 同上；包含Ozon方法资料 | 数据来源/时点、同币成本、箱单一致性、结算桥 | 作为方法来源；MPstats、平台及仓库连接分别验证，不能照搬其它履约规则 |
| [Nexscope eCommerce-Skills](https://github.com/nexscope-ai/eCommerce-Skills/tree/c5ba892a1cc3178626577aed1dbde5e62a82f1ac) | 新参考，首次静态复核 | 评论字段覆盖、痛点/优点、竞品矩阵、ABC库存与资金周期 | 择取字段及流程；利润脚本有静态公式不一致，采集/履约存在占位或指导，保留本项目经济模型和领域门禁 |
| [Oxylabs amazon-scraper](https://github.com/oxylabs/amazon-scraper/tree/ebc5d24559303dab835722f0a47282af24abab25) | 新参考，首次静态复核 | ASIN/子变体、地区/邮编/币种、页数费用与供应商请求身份 | 本机Selenium及商业API示例分开；Amazon阶段才评估可选数据源，未取得运行、计费和完整许可验证 |
| [Omkar Google Maps](https://github.com/omkarcloud/google-maps-scraper/tree/7eae385588a0320e51bb7a5193f53a7d30e896d8) | 新参考，首次静态复核 | 商家身份、地理分片、跨区域去重、渠道/仓库线索 | 当前公开树主要是文档和资产，没有可审查采集器实现；外部应用/API单独验证，地图线索不作为商品销量或正式供货证明 |

两 Sealeap 当前本地已登记797条技能索引、227细分模式、19个受限离线适配；这不表示797个可运行Agent。当前固定文件哈希与上游提交一致，不因仓库metadata updated_at变化就重复导入。Nexscope本轮固定树有162份SKILL.md、42份Python文件，抽查并验真16份原件；未逐行审查全部脚本。两个采集项目共固定并核验15份原件，未实采。

优先保留和增强现有证据、成本、预算、素材、任务、采购及上架领域，避免第二套后台、记忆与执行权限。每项借鉴先列明来源版本、输入前置、真实产出、缺项/UNKNOWN、运行范围和费用，再用合成样本验证；真实接入需要实际账户、范围及回读。

## 几个不能直接照用的例子

- Nexscope评论“真实性”分数是启发式，不能升级为事实核验；字段分层要逐字段检查，并保留原评论ID/引文/语言/窗口。其现词典没有俄语覆盖，中文也有翻译残片。[评论脚本](https://github.com/nexscope-ai/eCommerce-Skills/blob/c5ba892a1cc3178626577aed1dbde5e62a82f1ac/review-checker/amazon-review-checker/scripts/analyzer.py#L492-L533)。
- Nexscope利润脚本在同一费率口径下的盈亏平衡表达式不一致，调价函数遗漏其成本函数里的退货商品损失；不能替换本项目Decimal和未知费用HOLD。[计算脚本](https://github.com/nexscope-ai/eCommerce-Skills/blob/c5ba892a1cc3178626577aed1dbde5e62a82f1ac/profit-margin-calculator/profit-margin-calculator-amazon/scripts/calculator.py#L190-L287)。
- Oxylabs商品/搜索API例子没有完整的超时、持久回执、预算、原请求查询和UNKNOWN合同；Selenium搜索样例也不是可恢复的多页生产采集器。其当前完整树未发现LICENSE，不能因README的开源措辞默认许可。[源码](https://github.com/oxylabs/amazon-scraper/blob/ebc5d24559303dab835722f0a47282af24abab25/src/amazon_scraper/scraper.py)。
- Maps仓库的MIT原件只说明已审仓库文件，不能推导外部应用与商业服务采用相同授权；地理进度数也不能冒充最终去重后的独立商家数。[部署说明](https://github.com/omkarcloud/google-maps-scraper/blob/7eae385588a0320e51bb7a5193f53a7d30e896d8/server-deployment.md)。

## 对当前Ozon闭环的实际消化顺序

1. 已有Sealeap适配继续复用：来源时点、同币成本、报价/包装完整性和竞品变化；不重新安装同版本。
2. 经营预算与手机任务/决策先接原任务系统；预算不是每个Agent一份，任务入队不算动作完成。参见 [经营闭环合同](COMMERCE_AUTOMATION_BLUEPRINT.md)。
3. 有可信同SKU俄语评论后，择取字段覆盖及痛点矩阵；有准确SKU库存后，择取ABC/补货指标。无数据保持待补。
4. Amazon阶段再做有边界的供应商响应适配；Maps等实际渠道发现任务出现再验。均不从试运行预算自动购买订阅，也不用于绕过已受限站点。

Sealeap、Nexscope和Maps根许可原件为MIT；Oxylabs当前许可缺失。以上仅记录本轮可观察事实。详细提交、文件清单、哈希与算术对照保留在本机私有 `.local/agent-team/control/repo-audit/`，不将其静态观察宣传为运行或经营成功。
