import json
import os
import time
import random
import sys

# ========== 全局变量（由 main.py 注入）==========
player = {}
maps = {}
monsters = {}
npcs = {}
items = {}
quests = {}
skills = {}
shops = {}
trainers = {}
events = {}
config = {}
business = {}
DATA_DIR = ""
SAVE_FILE = ""

def init(core_data):
    """初始化核心模块，接收 main.py 传入的数据"""
    global player, maps, monsters, npcs, items, quests, skills, shops, trainers, events, config, business, DATA_DIR, SAVE_FILE
    player = core_data.get('player', {})
    maps = core_data.get('maps', {})
    monsters = core_data.get('monsters', {})
    npcs = core_data.get('npcs', {})
    items = core_data.get('items', {})
    quests = core_data.get('quests', {})
    skills = core_data.get('skills', {})
    shops = core_data.get('shops', {})
    trainers = core_data.get('trainers', {})
    events = core_data.get('events', {})
    config = core_data.get('config', {})
    business = core_data.get('business', {})
    DATA_DIR = core_data.get('DATA_DIR', '')
    SAVE_FILE = core_data.get('SAVE_FILE', '')
    
def save_player():
    with open(SAVE_FILE, 'w', encoding='utf-8') as f:
        json.dump(player, f, ensure_ascii=False, indent=2)

def show_status():
    print(f"\n[{player['name']}] LV.{player['level']} 经验:{player['exp']}/{player['level']*100}")
    print(f"❤️ HP:{player['hp']}/{player['max_hp']}  💙 MP:{player['mp']}/{player['max_mp']}")
    print(f"💰 银两:{player['money']}  📍 位置:{player['pos']}")

def look():
    if player['pos'] not in maps:
        print("❌ 位置异常")
        return
    
    map_data = maps[player['pos']]
    print(f"\n📍 【{player['pos']}】")
    print(f"   {map_data['desc']}")
    
    # 随机事件（每个事件用自己的概率）
    random_events = map_data.get('random_events', [])
    for re in random_events:
        chance = re.get('chance', 0)
        if random.random() < chance:
            from .events import trigger_event
            trigger_event(re.get('event'))
            time.sleep(0.2)  # 避免刷屏
    
    # 出口
    exits = map_data.get('exits', {})
    if exits:
        print(f"\n🚪 出口：{'、'.join(exits.keys())}")
    
    # NPC
    if map_data.get('npcs'):
        print(f"\n👤 见到的人物：{'、'.join(map_data['npcs'])}")
    
    # 怪物
    if map_data.get('monsters'):
        print(f"\n👹 游荡的怪物：{'、'.join(map_data['monsters'])}")
    
    # 谜题检测
    try:
        from . import puzzle
        puzzle.handle_puzzle_room()
    except:
        pass
        
def move(direction: str):
    if player['pos'] not in maps:
        print("❌ 位置异常")
        return
    
    map_data = maps[player['pos']]
    if direction in map_data.get('exits', {}):
        # 移动到新位置
        player['pos'] = map_data['exits'][direction]
        print(f"➡️ 移动到 {player['pos']}")
        
        # 👇 触发进入事件（关键！）
        new_map_data = maps.get(player['pos'], {})
        on_enter = new_map_data.get('on_enter')
        if on_enter:
            from .events import trigger_event
            trigger_event(on_enter)
        
        # 显示新位置
        look()
        save_player()
    else:
        print("❌ 那边走不通")

def show_direction_map():
    map_data = maps.get(player['pos'], {})
    exits = map_data.get('exits', {})
    dirs = []
    if "北" in exits:
        dirs.append(f"北 ↑ {exits['北']}")
    if "南" in exits:
        dirs.append(f"南 ↓ {exits['南']}")
    if "西" in exits:
        dirs.append(f"西 ← {exits['西']}")
    if "东" in exits:
        dirs.append(f"东 → {exits['东']}")
    if dirs:
        print(f"\n🚪 可前往：")
        for d in dirs:
            print(f"   {d}")
    else:
        print("\n🚪 这里没有出口")

# 在 core.py 末尾添加
def get_player():
    """获取当前玩家数据（确保是最新）"""
    global player
    return player

def set_player(new_player):
    """设置玩家数据"""
    global player
    player = new_player