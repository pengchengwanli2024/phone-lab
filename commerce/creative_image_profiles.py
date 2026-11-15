"""Image production targets; general references never approve publication."""
from copy import deepcopy

CHECKED_ON = '2026-11-15'
RATIOS = {'1:1': (2048, 2048), '3:4': (1536, 2048), '4:3': (2048, 1536)}
PROFILES = {
    'ozon_ru': {'label': 'Ozon · 俄罗斯', 'aspect_ratio': '3:4', 'max_images': 30,
        'verification': 'general_reference_category_confirmation_required',
        'note': '优先制作3:4；仍须确认本店类目的实际展示和上传规则。',
        'main_rule': '完整展示实际商品，背景不抢主体；不添加未经核实的品牌、参数或效果承诺。',
        'sources': ['https://seller.ozon.ru/media/boost/glavnoe-o-perehode-na-foto-3-4-v-kartochkah-otvechaem-na-populyarnye-voprosy-prodavcov/',
                    'https://seller.ozon.ru/media/boost/kak-sdelat-prodayushie-fotografii-tovara-dlya-marketplejsa/']},
    'amazon_us': {'label': 'Amazon · 美国', 'aspect_ratio': '1:1', 'max_images': None,
        'verification': 'general_reference_category_confirmation_required',
        'note': '主图和附图分别核对；最终以站点、类目和当前卖家规则为准。',
        'main_rule': '主图采用纯白背景RGB 255/255/255，完整商品占主要画面，不添加文字、水印或不随货配件。',
        'sources': ['https://sellercentral.amazon.com/help/hub/reference/external/G1881?locale=en_us']},
    'tiktok_us': {'label': 'TikTok Shop · 美国商品卡', 'aspect_ratio': '1:1', 'max_images': 9,
        'verification': 'general_reference_category_confirmation_required',
        'note': '商品卡最多9张方图，清晰展示实物，至少600×600；主图避免额外文字/图形。不是短视频或图文帖的9:16规格。',
        'main_rule': '主图清楚展示商品正面，不添加文字、图形、边框或模糊效果。',
        'sources': ['https://seller-us.tiktok.com/university/course?content_id=7073362639816491&lang=en&learning_id=7350062255294222']},
    'mercado_mx': {'label': 'Mercado Libre · 墨西哥', 'aspect_ratio': '1:1', 'max_images': None,
        'verification': 'store_or_category_rules_required',
        'note': '当前为制作母版；上传数量须读取实际类目的max_pictures_per_item，不套用其它平台上限。',
        'main_rule': '', 'sources': ['https://developers.mercadolibre.com.mx/en_us/tools/working-with-pictures']},
    'temu_us': {'label': 'Temu · 美国（规则待核对）', 'aspect_ratio': '1:1', 'max_images': None,
        'verification': 'store_or_category_rules_required', 'note': '先核对站点、经营模式和类目模板；当前仅制作母版。',
        'main_rule': '', 'sources': []},
    'shopify': {'label': 'Shopify · 按店铺主题核对', 'aspect_ratio': '1:1', 'max_images': None,
        'verification': 'store_or_category_rules_required', 'note': '按店铺主题的商品图库、裁切及移动端展示核对，不将制作比例当作平台强制比例。',
        'main_rule': '', 'sources': ['https://help.shopify.com/en/manual/products/product-media/product-media-types']},
    'woocommerce': {'label': 'WooCommerce · 按店铺主题核对', 'aspect_ratio': '1:1', 'max_images': None,
        'verification': 'store_or_category_rules_required', 'note': '主图、目录缩略图和图库受主题/图库组件设置影响，实际店铺配置待核对。',
        'main_rule': '', 'sources': ['https://woocommerce.com/document/adding-product-images-and-galleries/']},
    'unverified': {'label': '其它平台 / 规则待核对', 'aspect_ratio': '1:1', 'max_images': None,
        'verification': 'store_or_category_rules_required', 'note': '当前只设制作画幅，发布前另核对具体平台、站点和类目。',
        'main_rule': '', 'sources': []},
}


def catalog(default_profile='unverified'):
    return {'set_min': 5, 'set_max': 10, 'default_set_size': 6,
            'count_scope': 'planned_product_image_set_not_one_generation_call',
            'default_profile': default_profile if default_profile in PROFILES else 'unverified',
            'profiles': [{'id': key, **deepcopy(value), 'checked_on': CHECKED_ON,
                          'publication_approved': False} for key, value in PROFILES.items()]}


def normalize_options(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'profile_id', 'set_size', 'aspect_ratio', 'label', 'focus'}:
        raise ValueError('creative_image_options_invalid')
    profile = value.get('profile_id')
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError('creative_image_profile_unknown')
    count = value.get('set_size', 6)
    if type(count) is not int or not 5 <= count <= 10:
        raise ValueError('creative_image_set_size_invalid')
    if PROFILES[profile]['max_images'] is not None and count > PROFILES[profile]['max_images']:
        raise ValueError('creative_image_platform_count_exceeded')
    ratio = value.get('aspect_ratio')
    if ratio is not None and (not isinstance(ratio, str) or ratio not in RATIOS):
        raise ValueError('creative_image_options_invalid')
    if profile == 'tiktok_us' and ratio not in (None, '1:1'):
        raise ValueError('creative_image_platform_ratio_invalid')
    texts = {}
    for key, maximum in (('label', 120), ('focus', 1000)):
        text = value.get(key, '')
        if not isinstance(text, str) or len(text) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in text):
            raise ValueError('creative_image_options_invalid')
        texts[key] = text.strip()
    return {'profile_id': profile, 'set_size': count, 'aspect_ratio': ratio, **texts}


def apply_options(spec, options):
    if options is None:
        return spec
    if spec['format'].endswith('_video'):
        raise ValueError('creative_image_options_video_not_allowed')
    result = deepcopy(spec)
    profile = PROFILES[options['profile_id']]
    ratio = options['aspect_ratio'] or profile['aspect_ratio']
    result['width'], result['height'] = RATIOS[ratio]
    result['image_options'] = deepcopy(options)
    result['image_delivery'] = {'profile_id': options['profile_id'], **deepcopy(profile),
                                'aspect_ratio': ratio, 'checked_on': CHECKED_ON,
                                'planned_set_size': options['set_size'], 'publication_approved': False}
    result['prompt'] += '\n本套商品图计划共' + str(options['set_size']) + '张，各张独立制作；本次仍只生成一张，不把整套内容拼成一张。'
    result['prompt'] += '\n本张名称：' + (options['label'] or spec['label'])
    if options['focus']:
        result['prompt'] += '\n本张唯一内容重点：' + options['focus']
    result['prompt'] += '\n目标交付：' + profile['label'] + '；画幅' + ratio + '；' + profile['note']
    if spec['format'] == 'product_main' and profile['main_rule']:
        result['prompt'] += '\n本平台主图参考约束：' + profile['main_rule']
    result['prompt'] += '\n仅表达上方有依据的事实；平台通用参考不代表类目审核、素材权利或发布批准。'
    return result
