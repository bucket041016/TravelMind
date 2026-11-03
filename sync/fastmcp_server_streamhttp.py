# conda env mcp_env ,Python版本 3.10.18
# 关闭 proxy
# 使用方法：用python 把server启动

from datetime import datetime
from copy import deepcopy
import os
from pathlib import Path
import re
import threading
import time
import requests
from dotenv import load_dotenv
from fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

try:
    from knowledge import retrieve as retrieve_knowledge
except ModuleNotFoundError:  # pragma: no cover - 包方式导入时回退
    from sync.knowledge import retrieve as retrieve_knowledge

mcp = FastMCP(name="travel-agent-mcp")

AMAP_API_BASE = "https://restapi.amap.com"

CITY_ALIASES = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "南京": "Nanjing",
    "成都": "Chengdu",
    "重庆": "Chongqing",
    "西安": "Xian",
    "武汉": "Wuhan",
    "福州": "Fuzhou",
    "厦门": "Xiamen",
    "香港": "Hong Kong",
}

ROUTE_KNOWLEDGE = {
    ("福州", "厦门"): {
        "distance_km": 255,
        "duration": "约 1小时20分钟",
        "summary": "福州南站乘高铁到厦门北站，再换乘地铁/打车进入市区。",
        "steps": [
            "从福州市区前往福州南站",
            "乘坐福州南 -> 厦门北高铁",
            "到达厦门北后乘地铁 1 号线或打车前往酒店",
            "如果第一站去鼓浪屿，建议先到厦鼓码头附近寄存行李",
        ],
    },
    ("广州", "深圳"): {
        "distance_km": 137,
        "duration": "约 1小时",
        "summary": "广州南站乘高铁到深圳北站，适合周末短途出行。",
        "steps": [
            "从广州市区前往广州南站",
            "乘坐广州南 -> 深圳北高铁",
            "到达深圳北后乘地铁 4/5/6 号线进入核心商圈",
        ],
    },
    ("北京", "天津"): {
        "distance_km": 120,
        "duration": "约 35分钟",
        "summary": "北京南站乘京津城际到天津站，适合一日往返。",
        "steps": [
            "从北京市区前往北京南站",
            "乘坐京津城际到天津站",
            "从天津站步行或打车前往海河/意式风情区",
        ],
    },
}

RAIL_ROUTE_KNOWLEDGE = {
    ("广州", "深圳"): {
        "stations": "广州南/广州东 -> 深圳北/福田/深圳站",
        "duration": "约 30~75 分钟",
        "ticket": "二等座通常约 60~90 元，具体以 12306 为准",
        "frequency": "高铁和城际班次密集，适合周末短途",
        "advice": "首推高铁/城际：速度快、稳定、不需要考虑停车，落地后再换乘地铁或打车。",
    },
    ("福州", "厦门"): {
        "stations": "福州南/福州站 -> 厦门北/厦门站",
        "duration": "约 1 小时 20 分钟~2 小时",
        "ticket": "二等座通常约 70~110 元，具体以 12306 为准",
        "frequency": "动车和高铁班次较多，适合两日游",
        "advice": "优先选择到达厦门站或厦门北后接驳方便的车次，去鼓浪屿建议预留码头换乘时间。",
    },
    ("北京", "天津"): {
        "stations": "北京南 -> 天津/天津西",
        "duration": "约 30~45 分钟",
        "ticket": "二等座通常约 50~70 元，具体以 12306 为准",
        "frequency": "京津城际班次密集，适合一日往返",
        "advice": "首推京津城际，速度和稳定性都明显优于自驾。",
    },
}

POI_KNOWLEDGE = {
    "厦门": {
        "classic": ["鼓浪屿", "沙坡尾", "厦门园林植物园", "环岛路", "曾厝垵"],
        "food": ["八市海鲜", "沙茶面", "土笋冻", "烧肉粽", "花生汤"],
        "tips": ["鼓浪屿船票建议提前预约", "环岛路适合傍晚骑行", "植物园热带雨林区拍照效果好"],
    },
    "福州": {
        "classic": ["三坊七巷", "上下杭", "烟台山", "西湖公园", "鼓山"],
        "food": ["鱼丸", "肉燕", "佛跳墙", "锅边糊", "荔枝肉"],
        "tips": ["三坊七巷适合夜游", "烟台山适合拍照", "鼓山建议上午出发"],
    },
    "深圳": {
        "classic": ["深圳湾公园", "南山博物馆", "华侨城创意园", "莲花山公园", "欢乐港湾"],
        "food": ["潮汕牛肉火锅", "椰子鸡", "早茶", "客家菜", "海鲜大排档"],
        "tips": ["深圳湾日落很适合散步", "市内地铁覆盖较好", "周末热门商圈人流较多"],
    },
    "北京": {
        "classic": ["故宫", "景山公园", "什刹海", "颐和园", "国家博物馆"],
        "food": ["北京烤鸭", "炸酱面", "铜锅涮肉", "卤煮", "豆汁焦圈"],
        "tips": ["热门景点要提前预约", "雨天建议增加博物馆类室内路线", "早晚高峰尽量避开打车"],
    },
}

LOCAL_SPECIALTY_FOOD_KNOWLEDGE = {
    "厦门": [
        {"name": "沙茶面", "keywords": ["沙茶面"], "note": "厦门代表小吃，适合作为到达后的第一顿轻食。"},
        {"name": "海蛎煎", "keywords": ["海蛎煎", "蚵仔煎"], "note": "海鲜风味明显，适合搭配八市或中山路周边小吃线。"},
        {"name": "土笋冻", "keywords": ["土笋冻"], "note": "本地特色冷盘，口味特别，建议愿意尝鲜时安排。"},
        {"name": "姜母鸭", "keywords": ["姜母鸭"], "note": "更适合晚餐，香气浓、饱腹感强。"},
        {"name": "花生汤", "keywords": ["花生汤"], "note": "甜口小吃，适合下午茶或夜宵。"},
        {"name": "八市海鲜", "keywords": ["八市海鲜", "海鲜大排档"], "note": "适合多人一起吃，点菜前确认时价。"},
    ],
    "福州": [
        {"name": "鱼丸", "keywords": ["福州鱼丸"], "note": "福州经典小吃，适合早餐或行程间隙。"},
        {"name": "肉燕", "keywords": ["肉燕"], "note": "和鱼丸一起吃很顺路，适合安排在三坊七巷附近。"},
        {"name": "佛跳墙", "keywords": ["佛跳墙"], "note": "预算充足时可作为正餐亮点。"},
        {"name": "锅边糊", "keywords": ["锅边糊"], "note": "本地早餐代表，适合轻松开局。"},
        {"name": "荔枝肉", "keywords": ["荔枝肉"], "note": "酸甜口闽菜，适合不太能吃辣的人。"},
        {"name": "捞化", "keywords": ["捞化"], "note": "夜宵友好，行程结束后吃比较舒服。"},
    ],
    "深圳": [
        {"name": "潮汕牛肉火锅", "keywords": ["潮汕牛肉火锅"], "note": "深圳很常见的高质量晚餐选择，适合多人同行。"},
        {"name": "椰子鸡", "keywords": ["椰子鸡"], "note": "清爽不辣，适合第一晚或轻松行程。"},
        {"name": "广式早茶", "keywords": ["广式早茶", "早茶"], "note": "适合上午慢节奏安排，推荐避开周末正午排队。"},
        {"name": "客家菜", "keywords": ["客家菜"], "note": "适合想吃本地融合风味时选择。"},
        {"name": "海鲜大排档", "keywords": ["海鲜大排档"], "note": "适合夜晚聚餐，点菜前确认价格。"},
        {"name": "肠粉", "keywords": ["肠粉"], "note": "早餐和宵夜都合适，预算友好。"},
        {"name": "烧鹅", "keywords": ["烧鹅"], "note": "粤式正餐经典，适合和早茶或茶餐厅路线搭配。"},
    ],
    "广州": [
        {"name": "广式早茶", "keywords": ["广式早茶", "早茶"], "note": "广州美食核心体验，建议上午安排并提前取号。"},
        {"name": "肠粉", "keywords": ["肠粉"], "note": "早餐代表，预算友好且分布广。"},
        {"name": "云吞面", "keywords": ["云吞面"], "note": "适合作为轻便午餐。"},
        {"name": "烧鹅", "keywords": ["烧鹅"], "note": "粤式烧腊代表，适合正餐。"},
        {"name": "煲仔饭", "keywords": ["煲仔饭"], "note": "更适合晚餐，等待时间通常稍长。"},
        {"name": "双皮奶", "keywords": ["双皮奶"], "note": "甜品收尾，适合上下九或老城区路线。"},
        {"name": "牛杂", "keywords": ["牛杂"], "note": "街头小吃属性强，适合边逛边吃。"},
    ],
    "北京": [
        {"name": "北京烤鸭", "keywords": ["北京烤鸭"], "note": "北京正餐招牌，适合预算相对充足的一餐。"},
        {"name": "炸酱面", "keywords": ["炸酱面"], "note": "轻松省时，适合景点间午餐。"},
        {"name": "铜锅涮肉", "keywords": ["铜锅涮肉"], "note": "适合晚餐，冬天体验尤其好。"},
        {"name": "卤煮", "keywords": ["卤煮"], "note": "老北京风味重，建议愿意尝鲜时安排。"},
        {"name": "豆汁焦圈", "keywords": ["豆汁焦圈"], "note": "非常本地化，适合作为体验项而不是主餐。"},
    ],
    "上海": [
        {"name": "生煎", "keywords": ["生煎"], "note": "适合早餐或下午加餐。"},
        {"name": "小笼包", "keywords": ["小笼包"], "note": "游客友好，适合搭配豫园或人民广场路线。"},
        {"name": "本帮菜", "keywords": ["本帮菜"], "note": "偏甜口，适合正式晚餐。"},
        {"name": "葱油拌面", "keywords": ["葱油拌面"], "note": "简单省时，适合行程紧凑时。"},
        {"name": "排骨年糕", "keywords": ["排骨年糕"], "note": "老上海小吃，适合打卡体验。"},
    ],
    "杭州": [
        {"name": "西湖醋鱼", "keywords": ["西湖醋鱼"], "note": "杭州名菜，口味有争议，适合作为体验项。"},
        {"name": "龙井虾仁", "keywords": ["龙井虾仁"], "note": "清淡精致，适合正餐。"},
        {"name": "东坡肉", "keywords": ["东坡肉"], "note": "本帮杭帮菜代表，适合晚餐。"},
        {"name": "片儿川", "keywords": ["片儿川"], "note": "杭州面食代表，适合早餐或午餐。"},
        {"name": "葱包桧", "keywords": ["葱包桧"], "note": "街头小吃，适合顺路补充。"},
    ],
    "南京": [
        {"name": "鸭血粉丝汤", "keywords": ["鸭血粉丝汤"], "note": "南京代表小吃，适合早餐或午餐。"},
        {"name": "盐水鸭", "keywords": ["盐水鸭"], "note": "可以堂食也可打包，适合正餐加菜。"},
        {"name": "牛肉锅贴", "keywords": ["牛肉锅贴"], "note": "适合下午茶或夜宵。"},
        {"name": "皮肚面", "keywords": ["皮肚面"], "note": "本地面食代表，适合午餐。"},
        {"name": "梅花糕", "keywords": ["梅花糕"], "note": "甜口小吃，适合老门东路线。"},
    ],
    "成都": [
        {"name": "火锅", "keywords": ["成都火锅"], "note": "成都核心体验，建议晚餐安排并预留排队时间。"},
        {"name": "串串香", "keywords": ["串串香"], "note": "预算友好，适合夜宵。"},
        {"name": "担担面", "keywords": ["担担面"], "note": "适合午餐或小吃线。"},
        {"name": "钟水饺", "keywords": ["钟水饺"], "note": "甜辣口小吃，适合尝鲜。"},
        {"name": "甜水面", "keywords": ["甜水面"], "note": "成都特色面食，适合作为小吃组合。"},
    ],
    "重庆": [
        {"name": "重庆火锅", "keywords": ["重庆火锅"], "note": "重庆必吃，建议晚餐安排。"},
        {"name": "小面", "keywords": ["重庆小面"], "note": "早餐或午餐都合适，效率高。"},
        {"name": "酸辣粉", "keywords": ["酸辣粉"], "note": "适合解馋小吃。"},
        {"name": "江湖菜", "keywords": ["江湖菜"], "note": "口味重，适合能吃辣的人。"},
        {"name": "烤鱼", "keywords": ["重庆烤鱼"], "note": "适合多人晚餐。"},
    ],
    "西安": [
        {"name": "肉夹馍", "keywords": ["肉夹馍"], "note": "适合早餐或行程间隙。"},
        {"name": "羊肉泡馍", "keywords": ["羊肉泡馍"], "note": "饱腹感强，适合午餐。"},
        {"name": "凉皮", "keywords": ["凉皮"], "note": "清爽小吃，适合下午加餐。"},
        {"name": "biangbiang面", "keywords": ["biangbiang面"], "note": "陕西面食代表，适合正餐。"},
        {"name": "甑糕", "keywords": ["甑糕"], "note": "甜口早餐或小吃。"},
    ],
    "武汉": [
        {"name": "热干面", "keywords": ["热干面"], "note": "武汉早餐代表，适合第一天早上。"},
        {"name": "豆皮", "keywords": ["三鲜豆皮", "豆皮"], "note": "本地早餐经典。"},
        {"name": "鸭脖", "keywords": ["鸭脖"], "note": "适合作为伴手礼或夜宵。"},
        {"name": "武昌鱼", "keywords": ["武昌鱼"], "note": "适合正餐。"},
        {"name": "藕汤", "keywords": ["藕汤"], "note": "家常风味，适合不想吃太辣时。"},
    ],
    "天津": [
        {"name": "煎饼果子", "keywords": ["煎饼果子"], "note": "天津早餐代表，适合早上安排。"},
        {"name": "锅巴菜", "keywords": ["锅巴菜"], "note": "本地早餐，适合尝鲜。"},
        {"name": "狗不理包子", "keywords": ["狗不理包子"], "note": "知名度高但评价分化，适合作为打卡项。"},
        {"name": "耳朵眼炸糕", "keywords": ["耳朵眼炸糕"], "note": "甜口小吃，适合下午茶。"},
        {"name": "熟梨糕", "keywords": ["熟梨糕"], "note": "街头甜点，适合古文化街路线。"},
    ],
    "香港": [
        {"name": "港式茶餐厅", "keywords": ["茶餐厅"], "note": "体验密度高，适合早餐或午餐。"},
        {"name": "烧腊", "keywords": ["烧腊"], "note": "适合正餐，选择多。"},
        {"name": "云吞面", "keywords": ["云吞面"], "note": "轻便经典，适合行程紧凑时。"},
        {"name": "港式点心", "keywords": ["港式点心", "点心"], "note": "适合上午慢节奏。"},
        {"name": "鸡蛋仔", "keywords": ["鸡蛋仔"], "note": "街头小吃，适合边逛边吃。"},
    ],
    "长沙": [
        {"name": "臭豆腐", "keywords": ["长沙臭豆腐"], "note": "长沙小吃代表，适合放在夜市或步行街路线。"},
        {"name": "糖油粑粑", "keywords": ["糖油粑粑"], "note": "甜口小吃，适合下午或夜宵。"},
        {"name": "口味虾", "keywords": ["口味虾"], "note": "适合晚餐或夜宵，夏季体验更典型。"},
        {"name": "小炒黄牛肉", "keywords": ["小炒黄牛肉"], "note": "湘菜正餐代表，适合能吃辣的人。"},
        {"name": "剁椒鱼头", "keywords": ["剁椒鱼头"], "note": "适合多人共享，口味偏辣。"},
        {"name": "长沙米粉", "keywords": ["长沙米粉"], "note": "早餐友好，行程开局很合适。"},
    ],
    "苏州": [
        {"name": "苏式面", "keywords": ["苏式面", "苏州面馆"], "note": "适合早餐或午餐，浇头选择丰富。"},
        {"name": "松鼠桂鱼", "keywords": ["松鼠桂鱼"], "note": "苏帮菜代表，适合作为正餐亮点。"},
        {"name": "响油鳝糊", "keywords": ["响油鳝糊"], "note": "本地风味明显，适合想吃苏帮菜时安排。"},
        {"name": "糖粥", "keywords": ["糖粥"], "note": "甜口小吃，适合平江路或老城路线。"},
        {"name": "桂花鸡头米", "keywords": ["鸡头米"], "note": "季节性较强，秋季更值得找。"},
    ],
    "青岛": [
        {"name": "海鲜啤酒", "keywords": ["青岛海鲜", "啤酒屋"], "note": "适合晚餐，点海鲜前确认时价。"},
        {"name": "鲅鱼水饺", "keywords": ["鲅鱼水饺"], "note": "青岛特色主食，午晚餐都合适。"},
        {"name": "辣炒蛤蜊", "keywords": ["辣炒蛤蜊"], "note": "适合搭配啤酒和海鲜小馆。"},
        {"name": "海菜凉粉", "keywords": ["海菜凉粉"], "note": "清爽小吃，适合夏天。"},
        {"name": "排骨米饭", "keywords": ["排骨米饭"], "note": "本地日常餐，适合预算友好的一餐。"},
    ],
    "三亚": [
        {"name": "椰子鸡", "keywords": ["三亚椰子鸡"], "note": "清爽不辣，适合到达第一餐。"},
        {"name": "清补凉", "keywords": ["清补凉"], "note": "海南甜品，适合下午或夜宵。"},
        {"name": "海南粉", "keywords": ["海南粉"], "note": "早餐或轻食都合适。"},
        {"name": "文昌鸡", "keywords": ["文昌鸡"], "note": "海南经典正餐，适合多人共享。"},
        {"name": "海鲜大排档", "keywords": ["三亚海鲜大排档"], "note": "适合晚餐，建议明码标价后再点。"},
    ],
    "大理": [
        {"name": "乳扇", "keywords": ["乳扇"], "note": "大理特色小吃，适合尝鲜。"},
        {"name": "喜洲粑粑", "keywords": ["喜洲粑粑"], "note": "适合安排在喜洲古镇路线。"},
        {"name": "酸辣鱼", "keywords": ["大理酸辣鱼"], "note": "洱海周边正餐选择。"},
        {"name": "饵丝", "keywords": ["饵丝"], "note": "早餐友好，行程开始前吃很方便。"},
        {"name": "砂锅鱼", "keywords": ["砂锅鱼"], "note": "适合多人午晚餐。"},
    ],
    "丽江": [
        {"name": "腊排骨火锅", "keywords": ["腊排骨火锅"], "note": "丽江经典晚餐，适合多人同行。"},
        {"name": "鸡豆凉粉", "keywords": ["鸡豆凉粉"], "note": "本地小吃，适合古城闲逛时安排。"},
        {"name": "纳西烤鱼", "keywords": ["纳西烤鱼"], "note": "适合正餐，风味比较有辨识度。"},
        {"name": "黑山羊火锅", "keywords": ["黑山羊火锅"], "note": "适合天气偏冷或晚餐。"},
        {"name": "米灌肠", "keywords": ["米灌肠"], "note": "地方特色明显，适合愿意尝鲜的人。"},
    ],
    "昆明": [
        {"name": "过桥米线", "keywords": ["过桥米线"], "note": "昆明代表美食，适合午餐。"},
        {"name": "汽锅鸡", "keywords": ["汽锅鸡"], "note": "适合正餐，口味清鲜。"},
        {"name": "野生菌火锅", "keywords": ["野生菌火锅"], "note": "季节性较强，雨季更典型，务必选择正规餐厅。"},
        {"name": "豆花米线", "keywords": ["豆花米线"], "note": "早餐或轻食都合适。"},
        {"name": "鲜花饼", "keywords": ["鲜花饼"], "note": "适合买伴手礼或下午茶。"},
    ],
    "桂林": [
        {"name": "桂林米粉", "keywords": ["桂林米粉"], "note": "早餐和午餐都合适，是桂林最稳的特色选择。"},
        {"name": "啤酒鱼", "keywords": ["阳朔啤酒鱼", "啤酒鱼"], "note": "阳朔路线很适合安排。"},
        {"name": "荔浦芋扣肉", "keywords": ["荔浦芋扣肉"], "note": "适合多人正餐。"},
        {"name": "油茶", "keywords": ["桂林油茶"], "note": "本地风味强，适合尝鲜。"},
        {"name": "马蹄糕", "keywords": ["马蹄糕"], "note": "甜口小吃，适合饭后。"},
    ],
    "哈尔滨": [
        {"name": "锅包肉", "keywords": ["哈尔滨锅包肉"], "note": "东北菜代表，适合正餐。"},
        {"name": "红肠", "keywords": ["哈尔滨红肠"], "note": "可堂食也可买伴手礼。"},
        {"name": "铁锅炖", "keywords": ["铁锅炖"], "note": "适合多人晚餐，冬季尤其合适。"},
        {"name": "地三鲜", "keywords": ["地三鲜"], "note": "东北家常菜，接受度高。"},
        {"name": "大列巴", "keywords": ["大列巴"], "note": "适合作为伴手礼或早餐。"},
    ],
    "拉萨": [
        {"name": "藏面", "keywords": ["藏面"], "note": "适合早餐或轻午餐。"},
        {"name": "甜茶", "keywords": ["甜茶馆", "甜茶"], "note": "拉萨慢节奏体验，适合下午休整。"},
        {"name": "牦牛肉火锅", "keywords": ["牦牛肉火锅"], "note": "适合晚餐，饱腹感强。"},
        {"name": "酥油茶", "keywords": ["酥油茶"], "note": "地方特色强，建议少量尝试。"},
        {"name": "糌粑", "keywords": ["糌粑"], "note": "藏式特色主食，适合体验本地饮食。"},
    ],
    "贵阳": [
        {"name": "肠旺面", "keywords": ["肠旺面"], "note": "贵阳早餐代表，适合早上安排。"},
        {"name": "丝娃娃", "keywords": ["丝娃娃"], "note": "小吃属性强，适合多人尝鲜。"},
        {"name": "酸汤鱼", "keywords": ["酸汤鱼"], "note": "贵州风味正餐，适合晚餐。"},
        {"name": "豆腐圆子", "keywords": ["豆腐圆子"], "note": "街头小吃，适合边逛边吃。"},
        {"name": "牛肉粉", "keywords": ["牛肉粉"], "note": "早餐或午餐都合适。"},
    ],
    "扬州": [
        {"name": "扬州早茶", "keywords": ["扬州早茶"], "note": "扬州核心体验，建议上午慢慢吃。"},
        {"name": "大煮干丝", "keywords": ["大煮干丝"], "note": "淮扬菜代表，适合正餐。"},
        {"name": "狮子头", "keywords": ["扬州狮子头"], "note": "适合午晚餐，口味温和。"},
        {"name": "三丁包", "keywords": ["三丁包"], "note": "早茶常见，适合早餐。"},
        {"name": "扬州炒饭", "keywords": ["扬州炒饭"], "note": "游客友好，适合轻松一餐。"},
    ],
    "洛阳": [
        {"name": "洛阳水席", "keywords": ["洛阳水席"], "note": "洛阳代表宴席，适合多人正餐。"},
        {"name": "牛肉汤", "keywords": ["洛阳牛肉汤"], "note": "早餐很合适。"},
        {"name": "浆面条", "keywords": ["浆面条"], "note": "本地特色面食，适合午餐。"},
        {"name": "不翻汤", "keywords": ["不翻汤"], "note": "地方小吃，适合夜市或老城路线。"},
        {"name": "牡丹燕菜", "keywords": ["牡丹燕菜"], "note": "水席代表菜之一，适合体验项。"},
    ],
}

POI_FOOD_TYPES = "050000"
POI_SCENIC_TYPES = "110000"
POI_HOTEL_TYPES = "100000"
POI_DISPLAY_LIMIT = 8
POI_CANDIDATE_LIMIT = 18
POI_SPECIALTY_DISPLAY_LIMIT = 7
POI_SPECIALTY_KEYWORD_LIMIT = 3
POI_SPECIALTY_CANDIDATE_LIMIT = 5
POI_HOTEL_CANDIDATE_LIMIT = 10
POI_HOTEL_DISPLAY_LIMIT = 6
POI_SCENIC_DIVERSE_LIMIT = 24
POI_SCENIC_QUERY_LIMIT = 6
GENERIC_SPECIALTY_FOOD_PATTERNS = ("特色美食", "小吃", "老字号")

_AMAP_CACHE: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, dict]] = {}
_AMAP_REQUEST_LOCK = threading.Lock()
_AMAP_LAST_REQUEST_AT = 0.0
_AMAP_QPS_BACKOFF_SECONDS = (0.8, 1.6, 3.2)


def _sanitize_filename(filename: str) -> str:
    safe_name = re.sub(r"[^\w\-.]+", "_", filename.strip(), flags=re.UNICODE)
    return safe_name or f"itinerary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"


def _get_amap_key() -> str:
    return (
        os.getenv("AMAP_MAPS_API_KEY")
        or os.getenv("AMAP_API_KEY")
        or os.getenv("GAODE_API_KEY")
        or ""
    ).strip()


def _get_env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(value, minimum)


def _get_env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(value, minimum)


def _amap_cache_key(path: str, params: dict) -> tuple[str, tuple[tuple[str, str], ...]]:
    normalized_params = {**params, "output": "json"}
    return (
        path,
        tuple(
            sorted((str(key), str(value)) for key, value in normalized_params.items())
        ),
    )


def _get_cached_amap_response(cache_key: tuple[str, tuple[tuple[str, str], ...]], now: float) -> dict | None:
    cached = _AMAP_CACHE.get(cache_key)
    if not cached:
        return None
    expires_at, data = cached
    if expires_at <= now:
        _AMAP_CACHE.pop(cache_key, None)
        return None
    return deepcopy(data)


def _store_amap_response(cache_key: tuple[str, tuple[tuple[str, str], ...]], data: dict) -> None:
    ttl = _get_env_float("AMAP_CACHE_TTL_SECONDS", 600.0)
    if ttl <= 0:
        return

    if len(_AMAP_CACHE) >= _get_env_int("AMAP_CACHE_MAX_ITEMS", 256, minimum=16):
        oldest_key = min(_AMAP_CACHE, key=lambda key: _AMAP_CACHE[key][0])
        _AMAP_CACHE.pop(oldest_key, None)

    _AMAP_CACHE[cache_key] = (time.monotonic() + ttl, deepcopy(data))


def _is_amap_qps_error(info: str) -> bool:
    info_upper = info.upper()
    return "QPS" in info_upper or "CUQPS" in info_upper


def _wait_for_amap_slot_locked() -> None:
    global _AMAP_LAST_REQUEST_AT

    min_interval = _get_env_float("AMAP_MIN_REQUEST_INTERVAL_SECONDS", 0.45)
    now = time.monotonic()
    wait_seconds = min_interval - (now - _AMAP_LAST_REQUEST_AT)
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    _AMAP_LAST_REQUEST_AT = time.monotonic()


def _amap_get(path: str, params: dict) -> dict:
    key = _get_amap_key()
    if not key:
        raise RuntimeError("未配置高德 Key，请在 .env 中设置 AMAP_MAPS_API_KEY=你的高德 Web服务 Key。")

    cache_key = _amap_cache_key(path, params)
    max_retries = _get_env_int("AMAP_MAX_RETRIES", 3)
    attempts = max(1, max_retries + 1)

    with _AMAP_REQUEST_LOCK:
        cached = _get_cached_amap_response(cache_key, time.monotonic())
        if cached is not None:
            return cached

        last_error = ""
        for attempt in range(attempts):
            _wait_for_amap_slot_locked()

            try:
                response = requests.get(
                    f"{AMAP_API_BASE}{path}",
                    params={**params, "key": key, "output": "json"},
                    timeout=20,
                )
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                last_error = str(exc)
                if attempt < attempts - 1:
                    time.sleep(_AMAP_QPS_BACKOFF_SECONDS[min(attempt, len(_AMAP_QPS_BACKOFF_SECONDS) - 1)])
                    continue
                raise

            if str(data.get("status", "1")) == "1":
                _store_amap_response(cache_key, data)
                return deepcopy(data)

            info = str(data.get("info") or data.get("infocode") or "未知错误")
            last_error = info
            if _is_amap_qps_error(info) and attempt < attempts - 1:
                time.sleep(_AMAP_QPS_BACKOFF_SECONDS[min(attempt, len(_AMAP_QPS_BACKOFF_SECONDS) - 1)])
                continue

            raise RuntimeError(f"高德 API 调用失败：{info}")

    raise RuntimeError(f"高德 API 调用失败：{last_error or '未知错误'}")


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_distance(meters) -> str:
    meters_float = _to_float(meters)
    if meters_float <= 0:
        return "未知"
    if meters_float >= 1000:
        return f"{meters_float / 1000:.1f} km"
    return f"{meters_float:.0f} m"


def _format_duration(seconds) -> str:
    seconds_int = int(_to_float(seconds))
    if seconds_int <= 0:
        return "未知"
    minutes = round(seconds_int / 60)
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest_minutes = divmod(minutes, 60)
    return f"{hours} 小时 {rest_minutes} 分钟" if rest_minutes else f"{hours} 小时"


def _normalize_city_name(city: str) -> str:
    return re.sub(r"(市|城区|地区)$", "", str(city or "").strip())


def _parse_location(geocode: dict) -> tuple[str, str, str]:
    location = geocode.get("location", "")
    formatted_address = geocode.get("formatted_address") or geocode.get("name") or ""
    city = geocode.get("city") or geocode.get("province") or ""
    if isinstance(city, list):
        city = city[0] if city else ""
    return location, formatted_address, city


def _geocode_address(address: str, city: str = "") -> dict:
    data = _amap_get(
        "/v3/geocode/geo",
        {
            "address": address,
            **({"city": city} if city else {}),
        },
    )
    geocodes = data.get("geocodes") or []
    if not geocodes:
        raise RuntimeError(f"未能在高德地图中解析地址：{address}")
    return geocodes[0]


def _get_weather_from_amap(city: str, date: str) -> str:
    geocode = _geocode_address(city, city)
    adcode = geocode.get("adcode")
    if not adcode:
        raise RuntimeError(f"未能解析 {city} 的行政区划编码")

    target_index = 1 if "明天" in date or "tomorrow" in date.lower() else 0
    data = _amap_get(
        "/v3/weather/weatherInfo",
        {
            "city": adcode,
            "extensions": "all",
        },
    )
    forecasts = data.get("forecasts") or []
    casts = (forecasts[0].get("casts") if forecasts else []) or []

    if target_index < len(casts):
        cast = casts[target_index]
        return (
            f"{city}{date}天气（高德）：白天{cast.get('dayweather', '未知')}，"
            f"夜间{cast.get('nightweather', '未知')}；"
            f"气温 {cast.get('nighttemp', '未知')}~{cast.get('daytemp', '未知')}°C；"
            f"白天{cast.get('daywind', '未知')}风 {cast.get('daypower', '未知')}级。"
        )

    live_data = _amap_get(
        "/v3/weather/weatherInfo",
        {
            "city": adcode,
            "extensions": "base",
        },
    )
    lives = live_data.get("lives") or []
    if not lives:
        raise RuntimeError(f"高德未返回 {city} 天气")
    live = lives[0]
    return (
        f"{city}当前天气（高德）：{live.get('weather', '未知')}，"
        f"气温 {live.get('temperature', '未知')}°C，"
        f"湿度 {live.get('humidity', '未知')}%，"
        f"{live.get('winddirection', '未知')}风 {live.get('windpower', '未知')}级，"
        f"发布时间 {live.get('reporttime', '未知')}。"
    )


def _summarize_driving(data: dict, limit: int) -> list[str]:
    route = data.get("route", {})
    paths = route.get("paths") or []
    summaries = []
    selected_paths = paths[:limit]
    durations = [
        _to_float(path.get("duration") or (path.get("cost") or {}).get("duration"))
        for path in selected_paths
    ]
    toll_values = [
        _to_float(path.get("tolls") or (path.get("cost") or {}).get("tolls"), default=-1)
        for path in selected_paths
    ]
    valid_durations = [duration for duration in durations if duration > 0]
    best_duration = min(valid_durations) if valid_durations else 0
    valid_tolls = [
        toll
        for duration, toll in zip(durations, toll_values)
        if toll >= 0 and (not best_duration or duration <= best_duration * 1.35)
    ]
    if not valid_tolls:
        valid_tolls = [toll for toll in toll_values if toll >= 0]
    cheapest_toll = min(valid_tolls) if valid_tolls else -1

    for index, path in enumerate(selected_paths, start=1):
        cost = path.get("cost") or {}
        tolls = path.get("tolls") or cost.get("tolls")
        traffic_lights = path.get("traffic_lights") or cost.get("traffic_lights")
        duration_seconds = _to_float(path.get("duration") or cost.get("duration"))
        toll_value = _to_float(tolls, default=-1)
        traffic_light_count = int(_to_float(traffic_lights))
        tags = []
        if tolls:
            tags.append(f"过路费约 {tolls} 元")
        if traffic_lights:
            tags.append(f"红绿灯约 {traffic_lights} 个")
        tag_text = f"，{'，'.join(tags)}" if tags else ""
        summaries.append(
            f"{index}. 驾车路线：{_format_distance(path.get('distance'))}，"
            f"{_format_duration(duration_seconds)}{tag_text}。\n"
            f"   方案判断：{_driving_route_advice(duration_seconds, toll_value, traffic_light_count, best_duration, cheapest_toll)}"
        )

    return summaries


def _driving_route_advice(
    duration_seconds: float,
    tolls: float,
    traffic_lights: int,
    best_duration: float,
    cheapest_toll: float,
) -> str:
    signals = []

    if best_duration and duration_seconds <= best_duration * 1.08:
        signals.append("耗时最短梯队")
    elif best_duration and duration_seconds >= best_duration * 1.35:
        signals.append("耗时明显更长")
    else:
        signals.append("耗时中等")

    if tolls >= 0:
        if tolls <= 0:
            signals.append("基本无过路费")
        elif cheapest_toll >= 0 and tolls <= cheapest_toll + 8:
            signals.append("过路费较低")
        elif cheapest_toll >= 0 and tolls >= cheapest_toll + 20:
            signals.append("过路费偏高")

    if traffic_lights:
        if traffic_lights <= 10:
            signals.append("红绿灯少")
        elif traffic_lights >= 20:
            signals.append("市区/地面路段较多")

    if best_duration and duration_seconds <= best_duration * 1.08:
        scene = "赶时间、带行李或多人同行时优先考虑"
    elif tolls == 0 and best_duration and duration_seconds >= best_duration * 1.25:
        scene = "不赶时间且想省高速费时才考虑"
    elif traffic_lights >= 20:
        scene = "更适合作为备选，可能受市区拥堵影响"
    else:
        scene = "作为费用和耗时比较均衡的备选"

    return f"{'；'.join(signals)}。适合：{scene}。"


def _summarize_walking_or_bicycling(data: dict, mode_label: str, limit: int) -> list[str]:
    route = data.get("route", {})
    paths = route.get("paths") or []
    summaries = []

    for index, path in enumerate(paths[:limit], start=1):
        distance = _to_float(path.get("distance"))
        if distance > 5000:
            advice = f"{mode_label}距离偏长，更适合作为市内接驳参考，不建议作为主路线。"
        else:
            advice = f"适合最后一公里接驳或短距离慢行，注意天气和行李负担。"
        summaries.append(
            f"{index}. {mode_label}路线：{_format_distance(path.get('distance'))}，"
            f"{_format_duration(path.get('duration'))}。\n"
            f"   接驳提示：{advice}"
        )

    return summaries


def _summarize_transit(data: dict, limit: int) -> list[str]:
    route = data.get("route", {})
    transits = route.get("transits") or []
    summaries = []

    for index, transit in enumerate(transits[:limit], start=1):
        segments = transit.get("segments") or []
        lines = []
        walking_distance = 0.0

        for segment in segments:
            walking = segment.get("walking") or {}
            walking_distance += _to_float(walking.get("distance"))
            bus = segment.get("bus") or {}
            buslines = bus.get("buslines") or []
            for busline in buslines[:1]:
                name = busline.get("name")
                departure = (busline.get("departure_stop") or {}).get("name")
                arrival = (busline.get("arrival_stop") or {}).get("name")
                if name:
                    if departure and arrival:
                        lines.append(f"{name}（{departure} -> {arrival}）")
                    else:
                        lines.append(name)
            railway = segment.get("railway") or {}
            if railway.get("name"):
                lines.append(railway["name"])

        line_text = "；".join(lines[:4]) if lines else "暂无换乘线路详情"
        cost = transit.get("cost")
        cost_text = f"，票价约 {cost} 元" if cost else ""
        summaries.append(
            f"{index}. 公交换乘：{_format_distance(transit.get('distance'))}，"
            f"{_format_duration(transit.get('duration'))}{cost_text}，"
            f"步行约 {_format_distance(walking_distance)}。\n"
            f"   换乘方案：{line_text}"
        )

    return summaries


def _summarize_rail_route(origin_city: str, destination_city: str) -> list[str]:
    origin_key = _normalize_city_name(origin_city)
    destination_key = _normalize_city_name(destination_city)
    rail = RAIL_ROUTE_KNOWLEDGE.get((origin_key, destination_key))

    if rail:
        return [
            (
                f"1. 高铁/城际铁路：{rail['stations']}，车程{rail['duration']}。\n"
                f"   费用参考：{rail['ticket']}。\n"
                f"   班次特点：{rail['frequency']}。\n"
                f"   方案判断：{rail['advice']}"
            )
        ]

    route = ROUTE_KNOWLEDGE.get((origin_key, destination_key))
    if route:
        return [
            (
                f"1. 高铁/城际铁路建议：{origin_key} -> {destination_key}，预计{route['duration']}。\n"
                f"   路线摘要：{route['summary']}\n"
                "   方案判断：适合作为跨城主交通，具体车次、票价和余票请以 12306 为准。"
            )
        ]

    return [
        (
            f"1. 高铁/城际铁路：暂未内置 {origin_key} -> {destination_key} 的车站与票价信息。\n"
            "   方案判断：如果两地有高铁/动车直达，通常适合作为跨城主交通；车次、票价和余票请以 12306 为准。"
        )
    ]


def _call_amap_route(mode: str, origin: str, destination: str, city1: str, city2: str, limit: int) -> list[str]:
    if mode == "rail":
        return _summarize_rail_route(city1, city2)

    if mode == "driving":
        data = _amap_get(
            "/v5/direction/driving",
            {
                "origin": origin,
                "destination": destination,
                "show_fields": "cost,navi",
                "alternative_route": str(max(limit, 1)),
                "strategy": "32",
            },
        )
        return _summarize_driving(data, limit)

    if mode == "transit":
        data = _amap_get(
            "/v3/direction/transit/integrated",
            {
                "origin": origin,
                "destination": destination,
                "city": city1,
                "cityd": city2,
                "strategy": "0",
            },
        )
        return _summarize_transit(data, limit)

    if mode == "walking":
        data = _amap_get(
            "/v5/direction/walking",
            {
                "origin": origin,
                "destination": destination,
                "show_fields": "navi",
            },
        )
        return _summarize_walking_or_bicycling(data, "步行", limit)

    if mode == "bicycling":
        data = _amap_get(
            "/v5/direction/bicycling",
            {
                "origin": origin,
                "destination": destination,
                "show_fields": "navi",
            },
        )
        return _summarize_walking_or_bicycling(data, "骑行", limit)

    raise RuntimeError(f"不支持的高德路线模式：{mode}")

@mcp.tool()
def get_current_time() -> str:
    """获取当前时间

    Returns:
        str: 当前时间的字符串表示
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@mcp.tool()
def get_weather(city: str, date: str):
    """获取指定城市在特定日期的天气情况。

    Args:
        city (str): 需要查询天气的城市名称，例如 "北京" 或 "London"。
        date (str): 需要查询的日期，可以使用 "今天"、"明天" 等相对描述，或 "2023.10.27" 这样的具体日期。

    Returns:
        str: 包含该城市天气情况描述的原始文本。
    """
    try:
        if _get_amap_key():
            return _get_weather_from_amap(city, date)
    except Exception as amap_error:
        amap_error_text = str(amap_error)
    else:
        amap_error_text = ""

    endpoint = "https://wttr.in"
    query_city = CITY_ALIASES.get(city.strip(), city.strip())

    try:
        response = requests.get(
            f"{endpoint}/{query_city}",
            params={"format": "j1", "lang": "zh"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        target_index = 1 if "明天" in date or "tomorrow" in date.lower() else 0
        forecast_days = data.get("weather", [])
        current = data.get("current_condition", [{}])[0]

        if target_index < len(forecast_days):
            day = forecast_days[target_index]
            astronomy = day.get("astronomy", [{}])[0]
            hourly = day.get("hourly", [{}])
            noon = hourly[min(4, len(hourly) - 1)] if hourly else {}
            desc = noon.get("lang_zh", [{}])[0].get("value") or noon.get("weatherDesc", [{}])[0].get("value", "未知")
            return (
                f"{city}（{query_city}）{date}天气：{desc}。"
                f"气温 {day.get('mintempC', '未知')}~{day.get('maxtempC', '未知')}°C，"
                f"降水概率 {noon.get('chanceofrain', '未知')}%，"
                f"风速 {noon.get('windspeedKmph', '未知')} km/h，"
                f"日出 {astronomy.get('sunrise', '未知')}，日落 {astronomy.get('sunset', '未知')}。"
            )

        desc = current.get("lang_zh", [{}])[0].get("value") or current.get("weatherDesc", [{}])[0].get("value", "未知")
        return (
            f"{city}（{query_city}）当前天气：{desc}，"
            f"气温 {current.get('temp_C', '未知')}°C，"
            f"体感 {current.get('FeelsLikeC', '未知')}°C，"
            f"湿度 {current.get('humidity', '未知')}%。"
        )
    except Exception as e:
        fallback_note = f"高德天气失败：{amap_error_text}；" if amap_error_text else ""
        return (
            f"{city}{date}天气暂时无法实时获取：{fallback_note}备用天气源失败：{e}。"
            "建议出发前再次确认天气预警；短途出行可准备雨具、防晒和 1 小时机动时间。"
        )


@mcp.tool()
def amap_geocode(address: str, city: str = "") -> str:
    """调用高德地图地理编码，将地址转换为经纬度坐标。

    Args:
        address (str): 待解析地址，例如 "福州南站"、"厦门北站"、"广州塔"。
        city (str): 可选城市名，用于提升地址解析准确度，例如 "福州"。

    Returns:
        str: 地址、城市、经纬度坐标和行政区划编码。
    """
    try:
        geocode = _geocode_address(address, city)
        location, formatted_address, resolved_city = _parse_location(geocode)
        return (
            f"高德地理编码结果：{formatted_address or address}；"
            f"城市：{resolved_city or city or '未知'}；"
            f"坐标：{location}；"
            f"adcode：{geocode.get('adcode', '未知')}。"
        )
    except Exception as e:
        return f"高德地理编码失败：{e}"


@mcp.tool()
def amap_plan_routes(
    origin: str,
    destination: str,
    origin_city: str = "",
    destination_city: str = "",
    modes: str = "driving,transit",
    max_routes: int = 3,
) -> str:
    """调用高德地图路线规划，返回多种/多条出行路线和建议。

    Args:
        origin (str): 出发地地址或 POI，例如 "福州南站"、"广州市区"。
        destination (str): 目的地地址或 POI，例如 "厦门北站"、"深圳市中心"。
        origin_city (str): 出发城市，例如 "福州"。用于高德地理编码和公交跨城查询。
        destination_city (str): 目的城市，例如 "厦门"。用于高德地理编码和公交跨城查询。
        modes (str): 路线模式，逗号分隔，可选 rail, driving, transit, walking, bicycling。
        max_routes (int): 每种模式最多返回几条路线，建议 1 到 5。

    Returns:
        str: 多种出行方式的路线摘要，包括距离、耗时、费用/换乘、路线取舍和建议。
    """
    try:
        max_routes = max(1, min(int(max_routes), 5))
        origin_geocode = _geocode_address(origin, origin_city)
        destination_geocode = _geocode_address(destination, destination_city)
        origin_location, origin_address, resolved_origin_city = _parse_location(origin_geocode)
        destination_location, destination_address, resolved_destination_city = _parse_location(destination_geocode)

        if not origin_city:
            origin_city = resolved_origin_city
        if not destination_city:
            destination_city = resolved_destination_city

        requested_modes = [
            mode.strip().lower()
            for mode in modes.split(",")
            if mode.strip()
        ]
        if not requested_modes:
            requested_modes = ["driving", "transit"]

        mode_labels = {
            "rail": "高铁/城际铁路",
            "driving": "驾车",
            "transit": "公交/地铁",
            "walking": "步行",
            "bicycling": "骑行",
        }
        sections = [
            "高德路线规划结果",
            f"出发地：{origin_address or origin}（{origin_location}）",
            f"目的地：{destination_address or destination}（{destination_location}）",
        ]
        advice = []

        for mode in requested_modes:
            try:
                route_summaries = _call_amap_route(
                    mode,
                    origin_location,
                    destination_location,
                    origin_city,
                    destination_city,
                    max_routes,
                )
                if route_summaries:
                    sections.append(f"\n【{mode_labels.get(mode, mode)}】")
                    sections.extend(route_summaries)
                else:
                    sections.append(f"\n【{mode_labels.get(mode, mode)}】高德未返回可用路线。")
            except Exception as route_error:
                sections.append(f"\n【{mode_labels.get(mode, mode)}】查询失败：{route_error}")

        if "transit" in requested_modes:
            advice.append("公共交通适合不想开车、目的地靠近地铁/公交站时选择。")
        if "rail" in requested_modes:
            advice.append("高铁/城际适合作为跨城主交通，车次、票价和余票请以 12306 为准。")
        if "driving" in requested_modes:
            advice.append("驾车路线请结合实时路况、停车难度和过路费综合判断。")
        if "walking" in requested_modes or "bicycling" in requested_modes:
            advice.append("步行/骑行更适合同城短距离，跨城出行建议只作为市内接驳参考。")
        if advice:
            sections.append("\n出行建议：" + " ".join(advice))

        return "\n".join(sections)
    except Exception as e:
        return f"高德路线规划失败：{e}"


@mcp.tool()
def plan_route(origin: str, destination: str, transport_mode: str = "高铁") -> str:
    """规划两个城市之间的出行路线。

    Args:
        origin (str): 出发城市，例如 "福州"。
        destination (str): 目的地城市，例如 "厦门"。
        transport_mode (str): 交通方式，例如 "高铁"、"自驾"、"公共交通"。

    Returns:
        str: 路线摘要、距离、耗时和分步建议。
    """
    route = ROUTE_KNOWLEDGE.get((origin, destination))
    if not route:
        return (
            f"{origin} -> {destination} 路线建议：优先选择{transport_mode}或城际铁路。"
            "当前演示知识库暂无精确路线，建议补充地图 API 后获取实时距离、路况和换乘方案。"
        )

    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(route["steps"], start=1))
    return (
        f"{origin} -> {destination}，推荐交通方式：{transport_mode}。\n"
        f"距离：约 {route['distance_km']} 公里；预计耗时：{route['duration']}。\n"
        f"路线摘要：{route['summary']}\n"
        f"分步路线：\n{steps}"
    )


def _clean_amap_value(value) -> str:
    if value is None or value == [] or value == {}:
        return ""
    if isinstance(value, list):
        return "、".join(str(item) for item in value if item)
    return str(value).strip()


def _lookup_city_data(city: str, data_by_city: dict):
    city_text = re.sub(r"\s+", "", city or "")
    normalized = city_text.removesuffix("市").removesuffix("市区")
    candidates = [city_text, normalized]

    for candidate in candidates:
        if candidate in data_by_city:
            return data_by_city[candidate]

    for known_city, data in data_by_city.items():
        if known_city and (known_city in city_text or city_text in known_city):
            return data
    return None


def _get_city_poi_knowledge(city: str) -> dict | None:
    return _lookup_city_data(city, POI_KNOWLEDGE)


def _get_local_specialty_foods(city: str) -> list[dict]:
    return _lookup_city_data(city, LOCAL_SPECIALTY_FOOD_KNOWLEDGE) or []


def _resolve_poi_city(city: str) -> str:
    try:
        geocode = _geocode_address(city, city)
        return _clean_amap_value(geocode.get("adcode")) or city
    except Exception:
        return city


def _poi_interest_keyword(preference: str) -> tuple[str, str]:
    if re.search(r"博物馆|展览|室内", preference):
        return "博物馆", ""
    if re.search(r"亲子|孩子|小朋友", preference):
        return "亲子乐园", ""
    if re.search(r"海边|海景|沙滩", preference):
        return "海边", ""
    if re.search(r"夜景|夜游", preference):
        return "夜景", ""
    if re.search(r"拍照|出片|摄影", preference):
        return "景点", POI_SCENIC_TYPES
    return "景点", POI_SCENIC_TYPES


def _scenic_search_queries(preference: str) -> list[tuple[str, str]]:
    preference = str(preference or "")
    preferred: list[tuple[str, str]] = []
    if re.search(r"博物馆|展览|室内", preference):
        preferred.extend([("博物馆", ""), ("美术馆", ""), ("展览馆", "")])
    if re.search(r"亲子|孩子|小朋友", preference):
        preferred.extend([("主题乐园", ""), ("科技馆", ""), ("动物园", "")])
    if re.search(r"海边|海景|沙滩", preference):
        preferred.extend([("海滨", ""), ("海边", ""), ("码头", "")])
    if re.search(r"夜景|夜游", preference):
        preferred.extend([("夜景", ""), ("步行街", ""), ("商圈", "")])
    if re.search(r"拍照|出片|摄影", preference):
        preferred.extend([("创意园", ""), ("美术馆", ""), ("城市观光", "")])

    baseline = [
        _poi_interest_keyword(preference),
        ("博物馆", ""),
        ("历史文化", ""),
        ("创意园", ""),
        ("步行街", ""),
        ("海滨", ""),
        ("主题乐园", ""),
        ("夜景", ""),
    ]
    queries: list[tuple[str, str]] = []
    seen = set()
    for keyword, types in [*preferred, *baseline]:
        key = (keyword, types)
        if not keyword or key in seen:
            continue
        queries.append(key)
        seen.add(key)
        if len(queries) >= POI_SCENIC_QUERY_LIMIT:
            break
    return queries


def _is_park_like_poi(poi: dict) -> bool:
    text = f"{poi.get('name') or ''}{poi.get('type') or ''}"
    return any(keyword in text for keyword in ["公园", "园林", "湿地", "森林"])


def _is_unsuitable_scenic_poi(poi: dict) -> bool:
    name = _clean_amap_value(poi.get("name"))
    poi_type = _clean_amap_value(poi.get("type"))
    text = f"{name}{poi_type}"
    playable_shopping_keywords = ["步行街", "古镇", "创意园", "文化园", "欢乐港湾", "海上世界", "中英街", "老街", "街区", "商圈"]
    if any(keyword in poi_type for keyword in ["公司企业", "餐饮服务", "住宿服务"]):
        return True
    if "购物服务" in poi_type and not any(keyword in name for keyword in playable_shopping_keywords):
        return True
    if any(keyword in text for keyword in ["有限公司", "集团有限公司", "工程", "停车场", "售票处", "入口", "出口", "卫生间"]):
        return True
    return False


def _dedupe_poi_dicts(pois: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for poi in pois:
        if _is_unsuitable_scenic_poi(poi):
            continue
        name = _clean_amap_value(poi.get("name"))
        address = _clean_amap_value(poi.get("address"))
        location = _clean_amap_value(poi.get("location"))
        key = (_normalize_poi_name(name), address, location)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(poi)
    return deduped


def _search_diverse_scenic_pois(city: str, preference: str) -> tuple[list[dict], str]:
    buckets: list[list[dict]] = []
    query_labels = []
    for keyword, types in _scenic_search_queries(preference):
        try:
            pois = _amap_search_pois(city, keyword, types, limit=6)
        except Exception:
            continue
        pois = _dedupe_poi_dicts(pois)
        if not pois:
            continue
        buckets.append(pois)
        query_labels.append(keyword)

    non_park_candidates: list[dict] = []
    park_candidates: list[dict] = []
    seen = set()
    max_bucket = max((len(bucket) for bucket in buckets), default=0)
    for index in range(max_bucket):
        for bucket in buckets:
            if index >= len(bucket):
                continue
            poi = bucket[index]
            name = _clean_amap_value(poi.get("name"))
            address = _clean_amap_value(poi.get("address"))
            location = _clean_amap_value(poi.get("location"))
            key = (_normalize_poi_name(name), address, location)
            if not key[0] or key in seen:
                continue
            seen.add(key)
            if _is_park_like_poi(poi):
                park_candidates.append(poi)
            else:
                non_park_candidates.append(poi)

    mixed: list[dict] = []

    # 多元候选优先，公园作为真实 POI 补位；目标是避免前 5 个全是公园，而不是排斥公园。
    for poi in non_park_candidates[:5]:
        mixed.append(poi)
        if len(mixed) >= POI_SCENIC_DIVERSE_LIMIT:
            return mixed, "、".join(query_labels)

    remaining_non_parks = non_park_candidates[5:]
    while len(mixed) < POI_SCENIC_DIVERSE_LIMIT and (remaining_non_parks or park_candidates):
        if remaining_non_parks:
            mixed.append(remaining_non_parks.pop(0))
            if len(mixed) >= POI_SCENIC_DIVERSE_LIMIT:
                break
        if park_candidates:
            mixed.append(park_candidates.pop(0))

    return mixed, "、".join(query_labels)


def _amap_search_pois(
    city: str,
    keywords: str,
    types: str = "",
    limit: int = POI_CANDIDATE_LIMIT,
) -> list[dict]:
    data = _amap_get(
        "/v3/place/text",
        {
            "keywords": keywords,
            "city": _resolve_poi_city(city),
            "citylimit": "true",
            "children": "0",
            "offset": str(max(1, min(limit, 20))),
            "page": "1",
            "extensions": "all",
            **({"types": types} if types else {}),
        },
    )
    pois = data.get("pois") or []
    return pois[:limit]


def _normalize_poi_name(name: str) -> str:
    normalized = re.sub(r"[（(].*?[）)]", "", name)
    normalized = re.sub(r"[-—_·].*$", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.strip()


def _is_nested_poi_name(name: str, existing_names: list[str]) -> bool:
    normalized = _normalize_poi_name(name)
    if not normalized:
        return False

    for existing in existing_names:
        existing_normalized = _normalize_poi_name(existing)
        if not existing_normalized:
            continue
        if normalized == existing_normalized:
            return True
        if normalized.startswith(existing_normalized) or existing_normalized.startswith(normalized):
            return True
    return False


def _format_poi_items(
    pois: list[dict],
    limit: int = POI_DISPLAY_LIMIT,
    dedupe_nested: bool = False,
    dedupe_brand: bool = False,
) -> list[str]:
    lines = []
    seen = set()
    seen_names = []
    seen_brands = set()

    for poi in pois:
        name = _clean_amap_value(poi.get("name"))
        address = _clean_amap_value(poi.get("address"))
        district = _clean_amap_value(poi.get("adname") or poi.get("pname"))
        poi_type = _clean_amap_value(poi.get("type"))
        location = _clean_amap_value(poi.get("location"))
        biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
        rating = _clean_amap_value(biz_ext.get("rating"))
        cost = _clean_amap_value(biz_ext.get("cost"))
        photos = poi.get("photos") if isinstance(poi.get("photos"), list) else []
        photo_url = ""
        if photos:
            first_photo = photos[0] if isinstance(photos[0], dict) else {}
            photo_url = _clean_amap_value(first_photo.get("url"))

        if not name:
            continue

        key = (name, address)
        if key in seen:
            continue
        if dedupe_nested and _is_nested_poi_name(name, seen_names):
            continue
        brand_key = _normalize_poi_name(name)
        if dedupe_brand and brand_key and brand_key in seen_brands:
            continue

        seen.add(key)
        seen_names.append(name)
        if brand_key:
            seen_brands.add(brand_key)

        meta = []
        if district:
            meta.append(district)
        if rating and rating not in {"0", "0.0"}:
            meta.append(f"评分 {rating}")
        if cost and cost not in {"0", "0.0"}:
            meta.append(f"人均约 {cost} 元")
        if poi_type:
            meta.append(poi_type.split(";")[0])

        address_text = f"；地址：{address}" if address else ""
        location_text = f"；坐标：{location}" if location else ""
        photo_text = f"；图片：{photo_url}" if photo_url else ""
        meta_text = f"（{'，'.join(meta)}）" if meta else ""
        lines.append(f"{len(lines) + 1}. {name}{meta_text}{address_text}{location_text}{photo_text}")

        if len(lines) >= limit:
            break

    return lines


def _format_specialty_food_items(
    specialty_foods: list[dict],
    limit: int = POI_SPECIALTY_DISPLAY_LIMIT,
) -> list[str]:
    lines = []

    for item in specialty_foods:
        name = str(item.get("name") or "").strip()
        note = str(item.get("note") or "").strip()
        if not name:
            continue
        note_text = f"：{note}" if note else ""
        lines.append(f"{len(lines) + 1}. {name}{note_text}")
        if len(lines) >= limit:
            break

    return lines


def _city_keyword_prefix(city: str) -> str:
    city_text = re.sub(r"\s+", "", city or "")
    return city_text.removesuffix("市区").removesuffix("市")


def _generic_specialty_food_keywords(city: str) -> list[str]:
    city_prefix = _city_keyword_prefix(city)
    if not city_prefix:
        return list(GENERIC_SPECIALTY_FOOD_PATTERNS)
    return [f"{city_prefix}{pattern}" for pattern in GENERIC_SPECIALTY_FOOD_PATTERNS]


def _specialty_food_search_keywords(specialty_foods: list[dict], city: str = "") -> list[str]:
    keywords = []
    seen = set()

    for item in specialty_foods:
        item_keywords = item.get("keywords") or [item.get("name")]
        for keyword in item_keywords:
            keyword_text = str(keyword or "").strip()
            if not keyword_text or keyword_text in seen:
                continue
            keywords.append(keyword_text)
            seen.add(keyword_text)
            break
        if len(keywords) >= POI_SPECIALTY_KEYWORD_LIMIT:
            break

    return keywords or _generic_specialty_food_keywords(city)[:POI_SPECIALTY_KEYWORD_LIMIT]


def _amap_search_specialty_food_pois(city: str, specialty_foods: list[dict]) -> list[dict]:
    pois = []
    keywords = _specialty_food_search_keywords(specialty_foods, city)

    for keyword in keywords:
        try:
            pois.extend(
                _amap_search_pois(
                    city,
                    keyword,
                    POI_FOOD_TYPES,
                    limit=POI_SPECIALTY_CANDIDATE_LIMIT,
                )
            )
        except Exception:
            continue

    return pois


def _search_poi_with_amap(city: str, preference: str) -> str:
    scenic_keyword, scenic_types = _poi_interest_keyword(preference)
    scenic_pois, scenic_strategy = _search_diverse_scenic_pois(city, preference)
    if not scenic_pois:
        scenic_pois = _amap_search_pois(city, scenic_keyword, scenic_types)
        scenic_strategy = scenic_keyword
    food_pois = _amap_search_pois(city, "餐厅", POI_FOOD_TYPES)
    specialty_foods = _get_local_specialty_foods(city)
    specialty_pois = _amap_search_specialty_food_pois(city, specialty_foods)

    scenic_lines = _format_poi_items(scenic_pois, dedupe_nested=True)
    specialty_food_lines = _format_specialty_food_items(specialty_foods)
    specialty_place_lines = _format_poi_items(specialty_pois, dedupe_brand=True)
    food_lines = _format_poi_items(food_pois, dedupe_brand=True)

    if not scenic_lines and not specialty_food_lines and not specialty_place_lines and not food_lines:
        raise RuntimeError("高德未返回可用 POI。")

    specialty_keywords = "、".join(_specialty_food_search_keywords(specialty_foods, city))
    sections = [
        f"{city} 高德 POI 搜索结果（偏好：{preference}）",
        f"搜索策略：景点/活动使用多类型关键词「{scenic_strategy or scenic_keyword}」，地方特色关键词「{specialty_keywords}」，普通餐厅关键词「餐厅」，限定城市范围。",
    ]
    if scenic_lines:
        sections.append("\n【景点/活动】")
        sections.extend(scenic_lines)
    if specialty_food_lines:
        sections.append("\n【地方特色美食】")
        sections.extend(specialty_food_lines)
    elif specialty_place_lines:
        sections.append("\n【地方特色美食线索】")
        sections.append(f"1. 暂无「{city}」内置菜品知识，已改用高德关键词「{specialty_keywords}」检索特色店铺、老字号和小吃。")
        sections.append("2. 建议优先选择评分、人均、距离都合适的本地店，并把小吃/老字号安排在午餐、夜宵或景点之间。")
    if specialty_place_lines:
        sections.append("\n【特色店铺参考】")
        sections.extend(specialty_place_lines)
    if food_lines:
        sections.append("\n【美食/餐厅】")
        sections.extend(food_lines)
    sections.append("\n出行提示：特色美食来自城市知识库并结合高德 POI 搜索落地到店铺；评分、人均和营业状态可能随时间变化，热门餐厅建议提前取号或预约。")
    return "\n".join(sections)


def _search_poi_from_local(city: str, preference: str, reason: str = "") -> str:
    poi = _get_city_poi_knowledge(city)
    specialty_lines = _format_specialty_food_items(_get_local_specialty_foods(city))
    fallback_prefix = f"高德 POI 搜索暂不可用（{reason}），已降级到本地示例库。\n" if reason else ""
    if not poi:
        if specialty_lines:
            return "\n".join(
                [
                    f"{fallback_prefix}{city} 暂无内置景点数据，但已匹配到地方特色美食库。",
                    "\n【地方特色美食】",
                    *specialty_lines,
                    "\n出行提示：高德服务恢复后，Agent 会继续补充景点、特色店铺地址、评分和人均信息。",
                ]
            )

        generic_keywords = "、".join(_generic_specialty_food_keywords(city))
        return (
            f"{fallback_prefix}{city} 暂无内置 POI 数据。\n"
            "\n【地方特色美食线索】\n"
            f"1. 建议优先用「{generic_keywords}」作为高德检索关键词。\n"
            "2. 选择店铺时优先看评分、人均、距离和营业状态，少选跨城连锁店，多选本地小吃、老字号或美食街。\n"
            "3. 稍后恢复高德服务后，Agent 会自动给出对应店铺参考。"
        )

    tips = "；".join(poi["tips"])
    sections = [
        f"{fallback_prefix}{city} POI 推荐（偏好：{preference}）：",
        "\n【经典景点】",
        *[f"{index}. {name}" for index, name in enumerate(poi["classic"], start=1)],
    ]
    if specialty_lines:
        sections.extend(["\n【地方特色美食】", *specialty_lines])
    else:
        sections.extend(
            [
                "\n【美食推荐】",
                *[f"{index}. {name}" for index, name in enumerate(poi["food"], start=1)],
            ]
        )
    sections.append(f"\n出行提示：{tips}。")
    return "\n".join(sections)


@mcp.tool()
def search_poi(city: str, preference: str = "经典景点") -> str:
    """优先调用高德 POI 搜索查询目的地景点、美食和出行提示，失败时降级到本地示例库。

    Args:
        city (str): 目的地城市，例如 "厦门"。
        preference (str): 偏好类型，例如 "经典景点"、"美食"、"亲子"、"拍照"。

    Returns:
        str: 推荐景点、美食和提示。
    """
    if not _get_amap_key():
        return _search_poi_from_local(city, preference, "未配置高德 Key")

    try:
        return _search_poi_with_amap(city, preference)
    except Exception as exc:
        return _search_poi_from_local(city, preference, str(exc))


def _hotel_keyword_for_level(hotel_level: str) -> str:
    level = str(hotel_level or "").strip()
    if re.search(r"高端|豪华|五星", level):
        return "高端酒店"
    if re.search(r"经济|省钱|便宜|学生", level):
        return "经济型酒店"
    return "商务酒店"


def _is_unsuitable_hotel_poi(poi: dict, hotel_level: str) -> bool:
    level = str(hotel_level or "").strip()
    name = _clean_amap_value(poi.get("name"))
    poi_type = _clean_amap_value(poi.get("type"))
    text = f"{name}{poi_type}"
    if re.search(r"舒适|高端|豪华|五星", level):
        if re.search(r"青年旅舍|青旅|旅舍|招待所|旅馆|民宿|客栈|公寓", text):
            return True
    if re.search(r"高端|豪华|五星", level) and re.search(r"经济|快捷|精选|优选", text):
        return True
    return False


def _hotel_area_advice(city: str, hotel_level: str, near: str = "") -> str:
    level = str(hotel_level or "舒适").strip() or "舒适"
    if near:
        return f"优先选择{near}周边或地铁/打车 20 分钟内的{level}档酒店，减少第一天行李接驳。"
    return f"优先选择{city}核心商圈、地铁枢纽或第一天重点景点附近的{level}档酒店，兼顾交通和餐饮。"


def _search_hotels_from_local(city: str, hotel_level: str, reason: str = "", near: str = "") -> str:
    prefix = f"酒店 POI 搜索暂不可用（{reason}），已降级到规则建议。\n" if reason else ""
    area = _hotel_area_advice(city, hotel_level, near)
    level = str(hotel_level or "舒适").strip() or "舒适"
    candidates = [
        f"{city}核心商圈{level}档酒店区域（示例）：适合第一次到达、晚间觅食和公共交通接驳。",
        f"{city}地铁枢纽周边{level}档酒店区域（示例）：适合多日行程和跨区移动。",
        f"{city}重点景点附近{level}档酒店区域（示例）：适合慢节奏或亲子行程。",
    ]
    return "\n".join(
        [
            f"{prefix}{city} 酒店匹配结果（provider_status=not_configured）",
            f"住宿区域建议：{area}",
            "\n【酒店候选】",
            *[f"{index}. {item}" for index, item in enumerate(candidates, start=1)],
            "\n出行提示：当前不是实时酒店库存，不代表可预订价格或剩余房量；正式版本需接入酒店供应商接口。",
        ]
    )


@mcp.tool()
def search_hotels(city: str, hotel_level: str = "舒适", near: str = "", limit: int = 6) -> str:
    """搜索目的地城市酒店 POI，并按住宿档位给出候选区域和示例酒店。

    Args:
        city (str): 目的地城市，例如 "深圳"。
        hotel_level (str): 酒店档位，例如 "经济"、"舒适"、"高端"。
        near (str): 可选优先靠近的位置，例如 "深圳北站" 或 "鼓浪屿码头"。
        limit (int): 最多返回几个酒店候选。

    Returns:
        str: 酒店候选、住宿区域建议和实时库存说明。
    """
    limit = max(1, min(int(limit or POI_HOTEL_DISPLAY_LIMIT), POI_HOTEL_DISPLAY_LIMIT))
    area = _hotel_area_advice(city, hotel_level, near)

    if not _get_amap_key():
        return _search_hotels_from_local(city, hotel_level, "未配置高德 Key", near)

    keyword = _hotel_keyword_for_level(hotel_level)
    try:
        pois = _amap_search_pois(
            city,
            keyword,
            POI_HOTEL_TYPES,
            limit=POI_HOTEL_CANDIDATE_LIMIT,
        )
        filtered_pois = [poi for poi in pois if not _is_unsuitable_hotel_poi(poi, hotel_level)]
        hotel_lines = _format_poi_items(filtered_pois or pois, limit=limit, dedupe_brand=True)
        if not hotel_lines:
            raise RuntimeError("高德未返回酒店 POI。")
        return "\n".join(
            [
                f"{city} 酒店 POI 搜索结果（{hotel_level}档，provider_status=amap_fallback）",
                f"住宿区域建议：{area}",
                f"搜索策略：关键词「{keyword}」，限定城市范围；候选仅作位置和档位参考。",
                "\n【酒店候选】",
                *hotel_lines,
                "\n出行提示：酒店候选来自高德 POI，不代表实时房态、可订价格或平台库存；正式版本需接入酒店供应商接口。",
            ]
        )
    except Exception as exc:
        return _search_hotels_from_local(city, hotel_level, str(exc), near)



@mcp.tool()
def estimate_budget(origin: str, destination: str, days: int = 2, travelers: int = 1, hotel_level: str = "舒适") -> str:
    """估算一次城市短途出行的预算。

    Args:
        origin (str): 出发城市，例如 "福州"。
        destination (str): 目的地城市，例如 "厦门"。
        days (int): 出行天数。
        travelers (int): 出行人数。
        hotel_level (str): 酒店档位，例如 "经济"、"舒适"、"高端"。

    Returns:
        str: 按交通、住宿、餐饮、门票和市内交通拆分的预算估算。
    """
    hotel_price = {"经济": 220, "舒适": 380, "高端": 680}.get(hotel_level, 380)
    train_price = ROUTE_KNOWLEDGE.get((origin, destination), {}).get("distance_km", 180) * 0.6
    transport_total = round(train_price * 2 * travelers)
    hotel_total = hotel_price * max(days - 1, 1)
    food_total = 120 * days * travelers
    ticket_total = 160 * travelers
    local_total = 80 * days * travelers
    total = transport_total + hotel_total + food_total + ticket_total + local_total

    return (
        f"{origin} -> {destination} {days}天{travelers}人预算估算（{hotel_level}档）：\n"
        f"城际交通：约 {transport_total} 元；住宿：约 {hotel_total} 元；"
        f"餐饮：约 {food_total} 元；门票/体验：约 {ticket_total} 元；"
        f"市内交通：约 {local_total} 元；总计：约 {total} 元。"
    )


@mcp.tool()
def kb_retrieve(city: str, query: str = "", limit: int = 8) -> dict:
    """从人工策展的目的地知识库检索城市攻略与景点详情，用于补充高德不提供的背景事实。

    知识库只提供背景知识与解释（亮点、建议时长、预约规则、室内/雨天替代、本地贴士），
    不提供地点坐标、实时价格、库存或班次；真实地点与坐标仍由高德 POI 工具负责。

    Args:
        city (str): 目的地城市，例如 "深圳"。
        query (str): 可选检索词。为空时返回该城市攻略与全部景点条目；
            传入景点名时返回该景点及其相关条目的详情。
        limit (int): 返回条目上限，默认 8。

    Returns:
        dict: 城市攻略、命中条目与来源状态；城市未覆盖时 provider_status 为 not_covered。
    """
    try:
        return retrieve_knowledge(city, query=query, limit=limit)
    except Exception as exc:  # noqa: BLE001 - 工具不抛异常，降级为未覆盖
        return {
            "provider_status": "not_covered",
            "city": str(city or ""),
            "query": str(query or ""),
            "city_guide": None,
            "entries": [],
            "coverage": "none",
            "note": f"知识库检索失败：{exc}",
        }


@mcp.tool()
def write_itinerary_file(title: str, markdown_content: str, filename: str = "") -> str:
    """将生成的出行方案写入本地 Markdown 文件。

    Args:
        title (str): 行程标题。
        markdown_content (str): 完整的 Markdown 行程内容。
        filename (str): 可选文件名，例如 "xiamen_2days.md"。

    Returns:
        str: 文件保存路径。
    """
    output_dir = Path(__file__).resolve().parents[1] / "outputs"
    output_dir.mkdir(exist_ok=True)
    if not filename:
        filename = f"{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    file_path = output_dir / _sanitize_filename(filename)
    file_path.write_text(markdown_content, encoding="utf-8")
    return f"行程文件已生成：{file_path}"

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("MCP_PORT", "8098")),
        path="/my-custom-path",
        log_level="debug",
    )
