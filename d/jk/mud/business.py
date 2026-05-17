import random
import time
from . import core

def get_business(shop_name=None):
    """获取店铺数据"""
    if 'business' not in core.player:
        core.player['business'] = {}
    if not shop_name:
        return core.player['business']
    return core.player['business'].get(shop_name, {})

def save_business():
    """保存经营数据"""
    core.save_player()

def show_business_status(shop_name):
    """查看店铺状态"""
    business_data = get_business()
    if shop_name not in business_data:
        print(f"❌ 你没有店铺 {shop_name}")
        return
    
    shop = business_data[shop_name]
    config = core.business.get('shops', {}).get(shop_name, {})  # 👈 直接使用 core.business
    
    print(f"\n🏪 【{config.get('name', shop_name)}】")
    print(f"   等级: {shop.get('level', 1)}")
    print(f"   经验: {shop.get('exp', 0)}/{shop.get('exp_needed', 100)}")
    print(f"   现金: {shop.get('cash', 0)} 两")
    print(f"   声望: {shop.get('reputation', 50)}")
    print(f"\n📦 仓库：")
    warehouse = shop.get('warehouse', {})
    if warehouse:
        for item, qty in warehouse.items():
            product = core.business.get('products', {}).get(item, {})  # 👈 直接使用
            print(f"   • {product.get('name', item)} x{qty}")
    else:
        print("   空空如也")
    
    print(f"\n💰 昨日收入: {shop.get('daily_income', 0)} 两")
    print(f"💸 昨日支出: {shop.get('daily_cost', 0)} 两")

def buy_product(shop_name, product_name, quantity):
    """进货"""
    business_data = get_business()
    if shop_name not in business_data:
        print(f"❌ 你没有店铺 {shop_name}")
        return
    
    if 'products' not in core.business:  # 👈 直接判断
        print("❌ 经营数据未加载")
        return
    
    shop = business_data[shop_name]
    product = core.business['products'].get(product_name)
    if not product:
        print(f"❌ 没有 {product_name} 这个商品")
        return
    
    total_cost = product['buy_price'] * quantity
    if shop.get('cash', 0) < total_cost:
        print(f"❌ 现金不足！需要 {total_cost} 两，现有 {shop.get('cash', 0)} 两")
        return
    
    current_stock = sum(shop.get('warehouse', {}).values())
    max_stock = 100 + (shop.get('level', 1) - 1) * 50
    if current_stock + quantity > max_stock:
        print(f"❌ 仓库容量不足！最多能放 {max_stock - current_stock} 个")
        return
    
    shop['cash'] = shop.get('cash', 0) - total_cost
    if 'warehouse' not in shop:
        shop['warehouse'] = {}
    if product_name not in shop['warehouse']:
        shop['warehouse'][product_name] = 0
    shop['warehouse'][product_name] += quantity
    
    print(f"✅ 进货成功！花费 {total_cost} 两，获得 {product_name} x{quantity}")
    save_business()

def sell_product(shop_name, product_name, quantity):
    """卖出商品"""
    business_data = get_business()
    if shop_name not in business_data:
        print(f"❌ 你没有店铺 {shop_name}")
        return
    
    if 'products' not in core.business:
        print("❌ 经营数据未加载")
        return
    
    shop = business_data[shop_name]
    product = core.business['products'].get(product_name)
    if not product:
        print(f"❌ 没有 {product_name} 这个商品")
        return
    
    if shop.get('warehouse', {}).get(product_name, 0) < quantity:
        print(f"❌ 库存不足！只有 {shop.get('warehouse', {}).get(product_name, 0)} 个")
        return
    
    base_price = product['sell_price']
    reputation_bonus = 1 + (shop.get('reputation', 50) - 50) / 500
    price = int(base_price * reputation_bonus)
    
    total_income = price * quantity
    shop['cash'] = shop.get('cash', 0) + total_income
    shop['warehouse'][product_name] -= quantity
    
    if shop['warehouse'][product_name] <= 0:
        del shop['warehouse'][product_name]
    
    exp_gain = quantity * 2
    shop['exp'] = shop.get('exp', 0) + exp_gain
    check_level_up(shop_name, shop)
    
    print(f"✅ 卖出成功！获得 {total_income} 两，{product_name} x{quantity}")
    print(f"   📈 店铺经验 +{exp_gain}")
    save_business()

def check_level_up(shop_name, shop):
    """检查升级"""
    exp_needed = shop.get('exp_needed', 100)
    
    while shop.get('exp', 0) >= exp_needed:
        shop['level'] = shop.get('level', 1) + 1
        shop['exp'] = shop.get('exp', 0) - exp_needed
        shop['exp_needed'] = int(exp_needed * 1.5)
        
        print(f"\n🎉 恭喜！【{shop_name}】升级到 {shop['level']} 级！")
        
        reward = 100 * shop['level']
        shop['cash'] = shop.get('cash', 0) + reward
        print(f"   💰 获得升级奖励 {reward} 两")
        
        exp_needed = shop['exp_needed']

def next_day():
    """进入第二天（结算）"""
    business_data = get_business()
    
    if not business_data:
        print("❌ 没有店铺数据")
        return
    
    print("\n📅 新的一天开始了...")
    time.sleep(1)
    
    if 'market' in core.business and random.random() < 0.3:
        news = random.choice(core.business['market'].get('news', []))
        print(f"📰 {news}")
    
    total_income = 0
    total_cost = 0
    
    for shop_name, shop in business_data.items():
        config = core.business.get('shops', {}).get(shop_name, {})
        
        daily_income = 0
        warehouse = shop.get('warehouse', {}).copy()
        
        for product_name, qty in warehouse.items():
            product = core.business.get('products', {}).get(product_name, {})
            demand = product.get('demand', 10)
            sell_rate = min(0.5, demand / 100)
            sold = int(qty * sell_rate * random.uniform(0.8, 1.2))
            
            if sold > 0:
                price = product.get('sell_price', 10)
                daily_income += price * sold
                shop['warehouse'][product_name] -= sold
                if shop['warehouse'][product_name] <= 0:
                    del shop['warehouse'][product_name]
        
        daily_cost = config.get('daily_cost', 10)
        shop['cash'] = shop.get('cash', 0) + daily_income - daily_cost
        shop['daily_income'] = daily_income
        shop['daily_cost'] = daily_cost
        
        total_income += daily_income
        total_cost += daily_cost
        
        if daily_income > 0:
            print(f"\n🏪 {config.get('name', shop_name)}：收入 {daily_income} 两，支出 {daily_cost} 两")
    
    # 随机事件
    events = core.business.get('random_events', [])
    for event in events:
        if random.random() < event.get('chance', 0):
            print(f"\n🎲 {event.get('msg', '发生随机事件')}")
            if event.get('effect') == 'lose_money':
                for shop_name in business_data:
                    business_data[shop_name]['cash'] = business_data[shop_name].get('cash', 0) - event.get('amount', 0)
                    print(f"   💔 {shop_name} 损失 {event.get('amount', 0)} 两")
            elif event.get('effect') == 'big_order':
                for shop_name in business_data:
                    bonus = event.get('bonus', 0)
                    business_data[shop_name]['cash'] = business_data[shop_name].get('cash', 0) + bonus
                    print(f"   🎉 {shop_name} 额外收入 {bonus} 两")
    
    print(f"\n📊 今日总结：总收入 {total_income} 两，总支出 {total_cost} 两")
    print(f"💰 净收益 {total_income - total_cost} 两")
    
    save_business()

def show_market():
    """查看市场价格"""
    if 'products' not in core.business:
        print("❌ 经营数据未加载")
        return
    
    print("\n📈 市场价格：")
    for product_name, product in core.business['products'].items():
        price_variance = random.uniform(0.8, 1.2)
        current_buy = int(product['buy_price'] * price_variance)
        current_sell = int(product['sell_price'] * price_variance)
        print(f"   {product.get('name', product_name)}：收购 {current_buy} 两 | 售价 {current_sell} 两")