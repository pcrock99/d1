# mud各配置说明

## 一、maps.json - 地图配置

```json
{
  "地图ID": {
    "desc": "地图描述文字，玩家输入「看」时显示",
    "exits": {"北": "目标地图ID", "南": "目标地图ID", "东": "目标地图ID", "西": "目标地图ID"},
    "monsters": ["怪物ID1", "怪物ID2"],
    "npcs": ["NPC_ID1", "NPC_ID2"],
    "on_enter": "事件ID",
    "on_leave": "事件ID",
    "random_events": [
      {"chance": 0.1, "event": "事件ID"},
      {"chance": 0.05, "event": "事件ID"}
    ],
    "puzzle": {
      "id": "谜题ID",
      "type": "riddle",
      "question": "谜面问题",
      "answer": "答案",
      "hint": "提示文字",
      "success_msg": "破解成功消息",
      "on_solve": {
        "exits": {"新方向": "目标地图"},
        "msg": "额外消息"
      }
    },
    "type": "town"
  }
}
```

字段|说明|示例
:---:|:---:|:---:
desc|地图描述|"青石铺地，中央有棵老槐树"
exits|出口方向|{"北": "村北树林", "南": "村南"}
monsters|该地图出现的怪物|["偷鸡贼", "野狼"]
npcs|该地图出现的人物|["村长", "小贩"]
on_enter|进入时触发的事件|"welcome_msg"
on_leave|离开时触发的事件|"auto_save"
random_events|随机事件列表|{"chance": 0.1, "event": "find_coin"}
puzzle|谜题配置|见上
type|地图类型|town/wild/dungeon/puzzle

---

## 二、monsters.json - 怪物配置

```json
{
  "怪物ID": {
    "hp": 100,
    "attack": 25,
    "defense": 10,
    "exp": 50,
    "drops": ["物品ID1", "物品ID2"],
    "desc": "怪物描述"
  }
}
```

字段|说明|示例
:---:|:---:|:---:
hp|生命值|45
attack|攻击力|12
defense|防御力|3
exp|击败获得经验|30
drops|掉落物品列表|["鸡肉", "狼牙"]
desc|怪物描述|"一只灰色的野狼"

---

## 三、npcs.json - NPC配置

```json
{
  "NPC_ID": {
    "type": "normal",
    "dialog": "对话内容",
    "shop_id": "商店ID",
    "trainer_id": "师傅ID"
  }
}
```

字段|说明|可选值
:---:|:---:|:---:
type|NPC类型|normal(普通)/quest_giver(任务)/shop(商店)/trainer(师傅)
dialog|对话内容|字符串或数组或时间段对象
shop_id|商店ID（type=shop时用）|"杂货铺"
trainer_id|师傅ID（type=trainer时用）|"武师"

### dialog 三种格式

```json
// 单句话
"dialog": "少侠好！"

// 随机多句话
"dialog": ["话1", "话2", "话3"]

// 时间段不同的话
"dialog": {
  "早上": "早安！",
  "下午": "下午好！",
  "晚上": "晚安！",
  "default": "你好！"
}
```

---

## 四、items.json - 物品配置

```json
{
  "物品ID": {
    "type": "food",
    "price": 10,
    "desc": "物品描述",
    "hp_recover": 15,
    "mp_recover": 10,
    "attack": 5,
    "defense": 3,
    "slot": "weapon"
  }
}
```

字段|说明|适用类型
:---:|:---:|:---:
type|物品类型|food/potion/material/weapon/armor/accessory/treasure
price|价格|所有
desc|描述|所有
hp_recover|恢复生命|food, potion
mp_recover|恢复内力|food, potion
attack|攻击加成|weapon, accessory
defense|防御加成|armor, accessory
slot|装备位置|weapon/armor/accessory

---

## 五、quests.json - 任务配置

```json
{
  "任务ID": {
    "name": "任务名称",
    "desc": "任务描述",
    "from_npc": "发放NPC",
    "require_quest": "前置任务ID",
    "repeatable": true,
    "goal": {
      "type": "kill",
      "monster": "怪物ID",
      "target": 5
    },
    "reward": {
      "exp": 100,
      "money": 50,
      "item": "物品ID"
    }
  }
}
```

字段|说明|示例
:---:|:---:|:---:
name|任务名称|"除害·偷鸡贼"
desc|任务描述|"教训村口的偷鸡贼"
from_npc|发放任务的NPC|"村长"
require_quest|前置任务ID|"除害1"
repeatable|是否可重复|true/false
goal.type|目标类型|kill/collect/reach/talk
goal.monster|要杀的怪物|"偷鸡贼"
goal.item|要收集的物品|"兔毛"
goal.location|要到达的地图|"宝藏室"
goal.target|目标数量|5
reward.exp|奖励经验|100
reward.money|奖励银两|50
reward.item|奖励物品|"铁剑"

---

## 六、skills.json - 技能配置

```json
{
  "技能ID": {
    "type": "active",
    "cost_mp": 10,
    "damage_base": 30,
    "damage_variance": 8,
    "need_level": 2,
    "price": 100,
    "description": "技能描述"
  }
}
```

字段|说明|示例
:---:|:---:|:---:
type|技能类型|active(主动)/passive(被动)
cost_mp|MP消耗|8
damage_base|基础伤害|28
damage_variance|伤害波动|8
need_level|学习等级|2
price|学习价格|100
description|技能描述|"用力一击"

---

## 七、shops.json - 商店配置

```json
{
  "商店ID": {
    "items": [
      {"name": "物品ID", "price": 25},
      {"name": "物品ID", "price": 100}
    ]
  }
}
```

字段|说明|示例
:---:|:---:|:---:
items|商品列表|见上
name|物品ID|"金疮药"
price|售价|25

---

## 八、trainers.json - 师傅配置

```json
{
  "师傅ID": {
    "skills": [
      {"name": "技能ID", "price": 100, "need_level": 2}
    ]
  }
}
```

字段|说明|示例
:---:|:---:|:---:
skills|可学技能列表|见上
name|技能ID|"重击"
price|学习价格|100
need_level|需要等级|2

---

## 九、events.json - 事件配置

```json
{
  "事件ID": {
    "type": "message",
    "msg": "显示的消息",
    "item": "物品ID",
    "amount": 50,
    "monster": "怪物ID",
    "target": "地图ID"
  }
}
```

type|说明|必需字段
:---:|:---:|:---:
message|显示消息|msg
item|获得物品|item, msg
money|获得/失去银两|amount, msg
fight|触发战斗|monster, msg
teleport|传送|target, msg
save|自动存档|msg

---

## 十、business.json - 经营配置

```json
{
  "shops": {
    "店铺ID": {
      "name": "店铺名称",
      "daily_cost": 20
    }
  },
  "products": {
    "商品ID": {
      "name": "商品名称",
      "buy_price": 20,
      "sell_price": 35,
      "demand": 30
    }
  },
  "market": {
    "news": ["新闻1", "新闻2"]
  },
  "random_events": [
    {"chance": 0.1, "effect": "price_up", "msg": "物价上涨", "amount": 0}
  ]
}
```

字段|说明
:---:|:---:
shops|可经营的店铺
daily_cost|每日固定支出
products|可买卖的商品
buy_price|进货价
sell_price|售价
demand|市场需求（影响销量）
market.news|市场新闻随机库
random_events|经营随机事件

---

## 快速参考卡片

文件|作用|必须字段
:---:|:---:|:---:
maps.json|地图|desc
monsters.json|怪物|hp, attack, exp
npcs.json|NPC|type
items.json|物品|type, price
quests.json|任务|name, goal, reward
skills.json|技能|damage_base
shops.json|商店|items
trainers.json|师傅|skills
events.json|事件|type
business.json|经营|products