# modules/puzzle.py
import time
from . import core  # 👈 直接导入 core 模块

def get_puzzle_state():
    """获取谜题状态"""
    if 'puzzles' not in core.player:
        core.player['puzzles'] = {}
    return core.player['puzzles']

def solve_puzzle(puzzle_id):
    """标记谜题为已解"""
    state = get_puzzle_state()
    state[puzzle_id] = True
    core.save_player()
    print(f"   📜 谜题已记录在案")

def is_solved(puzzle_id):
    """检查谜题是否已解"""
    return core.player.get('puzzles', {}).get(puzzle_id, False)

def handle_puzzle_room():
    """处理谜题房间"""
    current_pos = core.player.get('pos')
    
    if not current_pos:
        return False
    
    # 直接使用 core.maps
    if current_pos not in core.maps:
        return False
    
    map_data = core.maps.get(current_pos, {})
    puzzle_config = map_data.get('puzzle')
    
    if not puzzle_config:
        return False
    
    puzzle_id = puzzle_config.get('id')
    
    # 如果已经解过
    if is_solved(puzzle_id):
        print(f"\n🔓 这里的谜题你已经破解过了")
        return False
    
    print(f"\n🔐 【{current_pos}】")
    print(f"   {map_data['desc']}")
    
    puzzle_type = puzzle_config.get('type', 'riddle')
    
    if puzzle_type == 'riddle':
        print(f"\n📜 墙壁上刻着一行字：")
        print(f"   \"{puzzle_config.get('question', '')}\"")
        if puzzle_config.get('hint'):
            print(f"\n   💡 输入「提示」获取帮助")
        print(f"   💡 输入「离开」放弃谜题")
        
        while True:
            answer = input("\n> 你的答案：").strip()
            
            if answer == "提示":
                print(f"\n   💡 {puzzle_config.get('hint', '没有提示')}")
            elif answer == "离开":
                print("\n   你放弃了谜题，决定日后再来")
                return True
            else:
                if answer == puzzle_config.get('answer'):
                    print(f"\n✨ {puzzle_config.get('success_msg', '谜题破解！')}")
                    solve_puzzle(puzzle_id)
                    
                    on_solve = puzzle_config.get('on_solve', {})
                    if 'exits' in on_solve:
                        core.maps[current_pos]['exits'] = on_solve['exits']
                        print(f"   🚪 新出口出现：{', '.join(on_solve['exits'].keys())}")
                    if 'msg' in on_solve:
                        print(f"   {on_solve['msg']}")
                    
                    core.save_player()
                    return True
                else:
                    print("\n   ❌ 答案错误，再试试看？")
    
    elif puzzle_type == 'code':
        print(f"\n🔒 一个古老的密码锁挡住了去路")
        print(f"   {puzzle_config.get('hint', '需要输入密码')}")
        max_attempts = puzzle_config.get('max_attempts', 3)
        attempts = 0
        
        while attempts < max_attempts:
            answer = input("\n> 输入密码：").strip()
            if answer == "离开":
                print("\n   你放弃了，决定日后再来")
                return True
            elif answer == puzzle_config.get('answer'):
                print(f"\n✨ {puzzle_config.get('success_msg', '密码正确，锁打开了！')}")
                solve_puzzle(puzzle_id)
                
                on_solve = puzzle_config.get('on_solve', {})
                if 'exits' in on_solve:
                    core.maps[current_pos]['exits'] = on_solve['exits']
                    print(f"   🚪 新出口出现：{', '.join(on_solve['exits'].keys())}")
                if 'msg' in on_solve:
                    print(f"   {on_solve['msg']}")
                
                core.save_player()
                return True
            else:
                attempts += 1
                print(f"\n   ❌ 密码错误，还剩 {max_attempts - attempts} 次机会")
        
        print("\n   💀 密码错误次数过多，锁死无法打开了")
        return True
    
    return True

def show_puzzles():
    """查看已解谜题"""
    state = get_puzzle_state()
    solved = [p for p, v in state.items() if v]
    if solved:
        print("\n🔓 已破解的谜题：")
        for p in solved:
            print(f"   • {p}")
    else:
        print("\n🔓 还没有破解任何谜题")