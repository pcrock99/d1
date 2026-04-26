#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线AI助手 - 命令行版本
不需要 Gradio，直接在终端运行
"""

import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

from pathlib import Path
import json
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

SCRIPT_DIR = Path(__file__).parent.absolute()
MODELS_DIR = SCRIPT_DIR / "models"
CONFIG_FILE = SCRIPT_DIR / "config.json"
MODELS_DIR.mkdir(exist_ok=True)

os.environ['HF_HOME'] = str(MODELS_DIR)
os.environ['TRANSFORMERS_CACHE'] = str(MODELS_DIR)

AVAILABLE_MODELS = [
    {"id": "phi3_mini", "name": "Phi-3 Mini 3.8B", "model_id": "microsoft/Phi-3-mini-4k-instruct", "size_gb": 7.8},
    {"id": "tiny_llama", "name": "TinyLlama 1.1B", "model_id": "TinyLlama/TinyLlama-1.1B-Chat-v0.3", "size_gb": 1.1},
    {"id": "qwen_1.8b", "name": "Qwen 1.8B", "model_id": "Qwen/Qwen-1.8B-Chat", "size_gb": 3.6},
]

class LocalAI:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.current_model = None
        self.history = []
    
    def load_model(self, model_id):
        cfg = next(m for m in AVAILABLE_MODELS if m["id"] == model_id)
        print(f"\n📥 加载模型: {cfg['name']} ({cfg['size_gb']}GB)")
        print(f"📁 保存位置: {MODELS_DIR}")
        print("⏳ 首次使用需要下载，请耐心等待...\n")
        
        try:
            print("🔧 加载 tokenizer...")
            self.tokenizer = AutoTokenizer.from_pretrained(
                cfg["model_id"], 
                trust_remote_code=True, 
                cache_dir=str(MODELS_DIR)
            )
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            print("📦 加载模型...")
            self.model = AutoModelForCausalLM.from_pretrained(
                cfg["model_id"], 
                torch_dtype=torch.float32, 
                trust_remote_code=True,
                cache_dir=str(MODELS_DIR), 
                low_cpu_mem_usage=True
            )
            self.current_model = cfg["id"]
            print(f"\n✅ 加载成功！可以开始对话了\n")
            return True
        except Exception as e:
            print(f"\n❌ 加载失败: {e}\n")
            return False
    
    def chat(self, user_input):
        if not self.model:
            return "请先加载模型（输入 1/2/3 选择模型）"
        
        try:
            prompt = f"用户: {user_input}\n助手:"
            inputs = self.tokenizer(prompt, return_tensors="pt", max_length=2048, truncation=True)
            outputs = self.model.generate(
                **inputs, 
                max_new_tokens=512, 
                temperature=0.7,
                top_p=0.95,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id
            )
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            # 提取助手回复
            if "助手:" in response:
                response = response.split("助手:")[-1].strip()
            return response if response else "(无回复)"
        except Exception as e:
            return f"错误: {e}"


def main():
    print("=" * 60)
    print("🤖 离线AI助手 - 命令行版")
    print(f"📁 模型目录: {MODELS_DIR}")
    print("=" * 60)
    
    ai = LocalAI()
    
    while True:
        print("\n" + "-" * 40)
        print("1. TinyLlama 1.1B (约1.1GB, 最快)")
        print("2. Qwen 1.8B (约3.6GB, 中文好)")
        print("3. Phi-3 Mini 3.8B (约7.8GB, 推荐)")
        print("0. 退出")
        print("-" * 40)
        
        choice = input("\n请选择模型: ").strip()
        
        if choice == "0":
            print("再见！")
            break
        elif choice in ["1", "2", "3"]:
            model_map = {"1": "tiny_llama", "2": "qwen_1.8b", "3": "phi3_mini"}
            if ai.load_model(model_map[choice]):
                print("\n" + "=" * 60)
                print("开始对话！输入 'quit' 退出，输入 'clear' 清除记忆，输入 'switch' 换模型")
                print("=" * 60 + "\n")
                
                while True:
                    user_input = input("你: ").strip()
                    if user_input.lower() == 'quit':
                        break
                    elif user_input.lower() == 'clear':
                        ai.history = []
                        print("✅ 记忆已清除\n")
                        continue
                    elif user_input.lower() == 'switch':
                        break
                    elif not user_input:
                        continue
                    
                    print("🤖 思考中...")
                    response = ai.chat(user_input)
                    print(f"\n🤖: {response}\n")
            else:
                print("加载失败，请重试")
        else:
            print("无效选择，请输入 1/2/3/0")

if __name__ == "__main__":
    main()