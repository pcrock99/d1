import random
import time
from . import core

def get_equip_bonus(attr):
    """计算装备加成"""
    bonus = 0
    for slot, item_name in core.player.get('equipment', {}).items():
        if item_name:
            item_data = core.items.get(item_name, {})
            bonus += item_data.get(attr, 0)
    return bonus

def fight(monster_name: str):
    if monster_name not in core.monsters:
        print(f"❌ 没见过这种怪物")
        return
    
    monster = core.monsters[monster_name]
    m_hp = monster['hp']
    m_max_hp = monster['hp']
    
    print(f"\n⚔️ 遭遇 {monster_name}！")
    print(f"   HP:{m_hp}/{m_max_hp} 攻击:{monster['attack']} 防御:{monster['defense']}")
    
    total_attack = core.player['attack'] + get_equip_bonus('attack')
    total_defense = core.player['defense'] + get_equip_bonus('defense')
    
    defending = False
    
    while core.player['hp'] > 0 and m_hp > 0:
        print(f"\n❤️ 你的HP:{core.player['hp']}/{core.player['max_hp']}  💙 MP:{core.player['mp']}/{core.player['max_mp']}")
        print(f"⚔️ 怪物HP:{m_hp}/{m_max_hp}")
        print("\n战斗选项：")
        print("  1. 攻击 (普通攻击)")
        print("  2. 技能 (消耗MP)")
        print("  3. 防御 (减少50%伤害)")
        print("  4. 逃跑 (有一定概率)")
        
        choice = input("\n> 选择行动：").strip()
        
        if choice in ["1", "攻击"]:
            damage = max(1, total_attack + random.randint(-3, 3) - monster['defense'])
            print(f"⚔️ 你发起攻击，造成 {damage} 伤害")
            m_hp -= damage
            defending = False
            
        elif choice in ["2", "技能"]:
            current_skill = core.player.get('skill', '普通攻击')
            skill_data = core.skills.get(current_skill, {})
            cost_mp = skill_data.get('cost_mp', 0)
            
            if core.player['mp'] >= cost_mp:
                core.player['mp'] -= cost_mp
                damage_base = skill_data.get('damage_base', total_attack)
                damage = max(1, damage_base + random.randint(-skill_data.get('damage_variance', 3), skill_data.get('damage_variance', 3)) - monster['defense'])
                print(f"✨ 使用 {current_skill}，消耗 {cost_mp} MP，造成 {damage} 伤害")
                m_hp -= damage
            else:
                print(f"❌ MP不足！改为普通攻击")
                damage = max(1, total_attack + random.randint(-3, 3) - monster['defense'])
                print(f"⚔️ 普通攻击，造成 {damage} 伤害")
                m_hp -= damage
            defending = False
            
        elif choice in ["3", "防御"]:
            print(f"🛡️ 你采取防御姿态，下回合受到的伤害减半")
            defending = True
            
        elif choice in ["4", "逃跑"]:
            if random.random() < 0.5:
                print("🏃 你成功逃跑了！")
                return
            else:
                print("😰 逃跑失败！")
                defending = False
        else:
            print("❌ 无效选择，改为普通攻击")
            damage = max(1, total_attack + random.randint(-3, 3) - monster['defense'])
            print(f"⚔️ 普通攻击，造成 {damage} 伤害")
            m_hp -= damage
            defending = False
        
        if m_hp <= 0:
            break
        
        monster_damage = max(1, monster['attack'] + random.randint(-2, 2) - total_defense)
        if defending:
            monster_damage = monster_damage // 2
            print(f"🛡️ 防御生效！")
        print(f"{monster_name} 攻击，造成 {monster_damage} 伤害")
        core.player['hp'] -= monster_damage
        defending = False
        time.sleep(0.5)
    
    if core.player['hp'] <= 0:
        print("💀 你倒下了...回到村口复活")
        core.player['hp'] = core.player['max_hp']
        core.player['mp'] = core.player['max_mp']
        core.player['pos'] = "新手村"
    else:
        exp_gain = monster['exp']
        core.player['exp'] += exp_gain
        print(f"🏆 胜利！获得 {exp_gain} 经验")
        
        if 'drops' in monster and random.random() < 0.4:
            item = random.choice(monster['drops'])
            if 'bag' not in core.player:
                core.player['bag'] = []
            core.player['bag'].append(item)
            print(f"📦 获得 {item}")
        
        exp_needed = core.player['level'] * 100
        while core.player['exp'] >= exp_needed:
            core.player['level'] += 1
            core.player['max_hp'] += 20
            core.player['max_mp'] += 15
            core.player['attack'] += 5
            core.player['defense'] += 2
            core.player['hp'] = core.player['max_hp']
            core.player['mp'] = core.player['max_mp']
            print(f"✨ 升级到 {core.player['level']} 级！")
            exp_needed = core.player['level'] * 100
        
        core.save_player()

def auto_grind(times: int = 5):
    print(f"🤖 自动模式启动，连续战斗 {times} 次")
    for i in range(times):
        if core.player['hp'] < core.player['max_hp'] * 0.3:
            print("⚠️ 血量过低，自动停止")
            break
        
        map_data = core.maps.get(core.player['pos'], {})
        if not map_data.get('monsters'):
            print("当前地图没有怪")
            break
        
        monster_name = random.choice(map_data['monsters'])
        monster = core.monsters[monster_name]
        m_hp = monster['hp']
        total_attack = core.player['attack'] + get_equip_bonus('attack')
        total_defense = core.player['defense'] + get_equip_bonus('defense')
        
        print(f"\n🤖 自动战斗 vs {monster_name}")
        while core.player['hp'] > 0 and m_hp > 0:
            damage = max(1, total_attack + random.randint(-3, 3) - monster['defense'])
            m_hp -= damage
            if m_hp <= 0:
                break
            monster_damage = max(1, monster['attack'] + random.randint(-2, 2) - total_defense)
            core.player['hp'] -= monster_damage
            time.sleep(0.3)
        
        if core.player['hp'] <= 0:
            print("💀 自动战斗失败...")
            core.player['hp'] = core.player['max_hp']
            core.player['mp'] = core.player['max_mp']
            core.player['pos'] = "新手村"
            break
        else:
            exp_gain = monster['exp']
            core.player['exp'] += exp_gain
            print(f"🏆 胜利！获得 {exp_gain} 经验")
            if 'drops' in monster and random.random() < 0.4:
                item = random.choice(monster['drops'])
                if 'bag' not in core.player:
                    core.player['bag'] = []
                core.player['bag'].append(item)
                print(f"📦 获得 {item}")
            
            exp_needed = core.player['level'] * 100
            while core.player['exp'] >= exp_needed:
                core.player['level'] += 1
                core.player['max_hp'] += 20
                core.player['max_mp'] += 15
                core.player['attack'] += 5
                core.player['defense'] += 2
                core.player['hp'] = core.player['max_hp']
                core.player['mp'] = core.player['max_mp']
                print(f"✨ 升级到 {core.player['level']} 级！")
                exp_needed = core.player['level'] * 100
            
            core.save_player()
        
        time.sleep(1)
    print("🤖 自动结束")

def meditate():
    print("\n🧘 你盘膝坐下，开始静心打坐...")
    rounds = 0
    while rounds < 10 and (core.player['hp'] < core.player['max_hp'] or core.player['mp'] < core.player['max_mp']):
        rounds += 1
        old_hp, old_mp = core.player['hp'], core.player['mp']
        core.player['hp'] = min(core.player['max_hp'], core.player['hp'] + 10)
        core.player['mp'] = min(core.player['max_mp'], core.player['mp'] + 5)
        hp_gain = core.player['hp'] - old_hp
        mp_gain = core.player['mp'] - old_mp
        if hp_gain > 0 or mp_gain > 0:
            print(f"   第{rounds}周天：恢复 ❤️+{hp_gain}  💙+{mp_gain}")
        else:
            break
        time.sleep(1)
    print("🧘 打坐结束")
    core.save_player()

def use_item(item_name):
    if item_name not in core.player.get('bag', []):
        print(f"❌ 你身上没有 {item_name}")
        return
    
    item_data = core.items.get(item_name, {})
    item_type = item_data.get('type')
    
    if item_type in ['food', 'potion']:
        hp_recover = item_data.get('hp_recover', 0)
        
        if hp_recover > 0:
            old_hp = core.player['hp']
            core.player['hp'] = min(core.player['max_hp'], core.player['hp'] + hp_recover)
            actual_hp = core.player['hp'] - old_hp
            print(f"❤️ 恢复了 {actual_hp} 点生命")
        
        core.player['bag'].remove(item_name)
        print(f"📦 消耗了 {item_name}")
        core.save_player()
    else:
        print(f"❌ {item_name} 无法使用")

def show_equipment():
    print("\n⚔️ 当前装备：")
    slot_names = {"weapon": "武器", "body": "衣服", "feet": "鞋子", "ring": "戒指"}
    for slot, name in slot_names.items():
        item_name = core.player.get('equipment', {}).get(slot)
        if item_name:
            print(f"   {name}: {item_name}")
        else:
            print(f"   {name}: 无")

def equip_item(item_name):
    if item_name not in core.player['bag']:
        print(f"❌ 你身上没有 {item_name}")
        return
    
    item_data = core.items.get(item_name, {})
    if item_data.get('type') not in ['weapon', 'armor', 'accessory']:
        print(f"❌ {item_name} 不是装备")
        return
    
    slot = item_data.get('slot')
    if not slot:
        print("❌ 无法确定装备位置")
        return
    
    if 'equipment' not in core.player:
        core.player['equipment'] = {}
    
    old_item = core.player['equipment'].get(slot)
    if old_item:
        core.player['bag'].append(old_item)
    
    core.player['equipment'][slot] = item_name
    core.player['bag'].remove(item_name)
    print(f"✅ 装备成功：{item_name}")
    core.save_player()

def unequip_item(slot_name):
    slot_map = {"武器": "weapon", "衣服": "body", "鞋子": "feet", "戒指": "ring"}
    slot = slot_map.get(slot_name)
    if not slot:
        print("❌ 请指定：武器/衣服/鞋子/戒指")
        return
    
    item_name = core.player.get('equipment', {}).get(slot)
    if not item_name:
        print(f"❌ 当前没有装备 {slot_name}")
        return
    
    core.player['equipment'][slot] = None
    core.player['bag'].append(item_name)
    print(f"✅ 脱下装备：{item_name}")
    core.save_player()

def learn_skill(npc_name):
    """查看NPC可学的武功"""
    # 检查NPC是否在当前地图
    map_data = core.maps.get(core.player['pos'], {})
    if npc_name not in map_data.get('npcs', []):
        print(f"❌ 这里没有 {npc_name}")
        return
    
    npc_data = core.npcs.get(npc_name, {})
    if npc_data.get('type') != 'trainer':
        print(f"❌ {npc_name} 不会武功")
        return
    
    trainer_id = npc_data.get('trainer_id', npc_name)
    trainer = core.trainers.get(trainer_id, {})
    skill_list = trainer.get('skills', [])
    
    if not skill_list:
        print(f"❌ {npc_name} 没什么可教的")
        return
    
    print(f"\n📖 {npc_name} 传授的武功：")
    for skill in skill_list:
        skill_name = skill.get('name')
        skill_data = core.skills.get(skill_name, {})
        need_lv = skill.get('need_level', skill_data.get('need_level', 1))
        price = skill.get('price', skill_data.get('price', 100))
        
        can_learn = (core.player['level'] >= need_lv and skill_name not in core.player.get('learned_skills', []))
        status = "✅可学" if can_learn else "❌"
        
        if skill_name in core.player.get('learned_skills', []):
            need_text = "已学会"
        else:
            need_text = f"需要{need_lv}级"
        
        print(f"   • {skill_name} - {price}两 ({need_text}) {status}")

def do_learn(skill_name):
    """执行学习武功"""
    # 找到能教这个技能的NPC
    teacher_npc = None
    teacher_data = None
    
    for npc_name, npc_info in core.npcs.items():
        if npc_info.get('type') == 'trainer':
            trainer_id = npc_info.get('trainer_id', npc_name)
            trainer = core.trainers.get(trainer_id, {})
            for skill in trainer.get('skills', []):
                if skill.get('name') == skill_name:
                    teacher_npc = npc_name
                    teacher_data = skill
                    break
        if teacher_npc:
            break
    
    if not teacher_npc:
        print(f"❌ 没人能教 {skill_name}")
        return
    
    # 检查NPC是否在当前地图
    map_data = core.maps.get(core.player['pos'], {})
    if teacher_npc not in map_data.get('npcs', []):
        print(f"❌ {teacher_npc} 不在这里")
        return
    
    if skill_name in core.player.get('learned_skills', []):
        print("❌ 你已经会这个武功了")
        return
    
    need_lv = teacher_data.get('need_level', 1)
    price = teacher_data.get('price', 100)
    
    if core.player['level'] < need_lv:
        print(f"❌ 等级不够，需要 {need_lv} 级")
        return
    
    if core.player['money'] < price:
        print(f"❌ 银两不足，需要 {price} 两")
        return
    
    core.player['money'] -= price
    if 'learned_skills' not in core.player:
        core.player['learned_skills'] = []
    core.player['learned_skills'].append(skill_name)
    
    print(f"✨ 恭喜！学会武功：【{skill_name}】")
    print(f"   消耗 {price} 两")
    print(f"   输入「用 {skill_name}」切换使用")
    core.save_player()

def list_skills():
    print(f"\n📚 已学武功：")
    for s in core.player.get('learned_skills', []):
        current = "【当前】" if s == core.player.get('skill') else ""
        print(f"   • {s} {current}")

def switch_skill(skill_name):
    if skill_name in core.player.get('learned_skills', []):
        core.player['skill'] = skill_name
        print(f"⚔️ 切换为：【{skill_name}】")
        core.save_player()
    else:
        print(f"❌ 你还不会 {skill_name}")

def show_bag():
    if not core.player.get('bag'):
        print("🎒 背包空空如也")
    else:
        print("🎒 背包：")
        for item in set(core.player['bag']):
            count = core.player['bag'].count(item)
            item_data = core.items.get(item, {})
            desc = item_data.get('desc', '')
            print(f"   • {item} x{count} - {desc}")
    
    print(f"\n💰 银两：{core.player.get('money', 0)}")
    print("💡 输入「用 物品名」使用物品")

def talk_to(npc: str):
    map_data = core.maps.get(core.player['pos'], {})
    if npc not in map_data.get('npcs', []):
        print(f"❌ 这里没有 {npc}")
        return
    
    npc_data = core.npcs.get(npc, {})
    npc_type = npc_data.get('type', 'normal')
    
    for qid, quest in core.quests.items():
        if quest.get('from_npc') == npc:
            if qid not in core.player.get('quests', {}):
                core.player['quests'][qid] = "doing"
                print(f"📜 接到任务：【{quest['name']}】")
                return
    
    dialog = npc_data.get('dialog', '少侠好！')
    if isinstance(dialog, list):
        dialog = random.choice(dialog)
    elif isinstance(dialog, dict):
        hour = time.localtime().tm_hour
        if hour < 12:
            dialog = dialog.get('早上', dialog.get('default', '少侠好！'))
        else:
            dialog = dialog.get('下午', dialog.get('default', '少侠好！'))
    
    print(f"💬 {npc}：\"{dialog}\"")
    if npc_type == 'shop':
        print("   输入「看店 " + npc + "」查看商品")
    elif npc_type == 'trainer':
        print("   输入「学艺 " + npc + "」查看可学武功")

def show_shop(npc_name):
    npc_data = core.npcs.get(npc_name, {})
    shop_id = npc_data.get('shop_id')
    if not shop_id or shop_id not in core.shops:
        print(f"❌ {npc_name} 这里不卖东西")
        return
    
    shop = core.shops[shop_id]
    print(f"\n🏪 {npc_name} 的货物：")
    for i, item in enumerate(shop.get('items', []), 1):
        item_data = core.items.get(item['name'], {})
        print(f"   {i}. {item['name']} - {item['price']}两")

def buy_item(item_name):
    for shop_id, shop in core.shops.items():
        for item in shop.get('items', []):
            if item['name'] == item_name:
                if core.player['money'] >= item['price']:
                    core.player['money'] -= item['price']
                    if 'bag' not in core.player:
                        core.player['bag'] = []
                    core.player['bag'].append(item_name)
                    print(f"✅ 购买成功！获得 {item_name}")
                    core.save_player()
                    return
                else:
                    print(f"❌ 银两不足")
                    return
    print(f"❌ 买不到 {item_name}")