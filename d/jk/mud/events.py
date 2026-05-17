import time
from . import core

def trigger_event(event_id):
    """触发事件"""
    events = core.events
    player = core.get_player()  # 👈 用 get_player 获取最新数据
    
    event = events.get(event_id)
    if not event:
        print(f"⚠️ 事件不存在：{event_id}")
        return
    
    event_type = event.get('type')
    
    if event_type == 'message':
        print(event.get('msg', ''))
        
    elif event_type == 'item':
        item = event.get('item')
        if item:
            if 'bag' not in player:
                player['bag'] = []
            player['bag'].append(item)
            print(event.get('msg', f'📦 获得 {item}'))
            core.save_player()
            
    elif event_type == 'money':
        amount = event.get('amount', 0)
        if 'money' not in player:
            player['money'] = 0
        player['money'] += amount
        print(event.get('msg', f'💰 获得 {amount} 两'))
        core.save_player()
        
    elif event_type == 'fight':
        monster = event.get('monster')
        if monster:
            print(event.get('msg', f'⚔️ {monster} 出现了！'))
            from . import rpg
            rpg.fight(monster)
    
    elif event_type == 'save':
        core.save_player()
        print(event.get('msg', '💾 已保存'))
    
    elif event_type == 'teleport':
        target = event.get('target')
        if target and target in core.maps:
            player['pos'] = target
            print(event.get('msg', f'✨ 被传送到 {target}'))
            core.save_player()
            core.look()