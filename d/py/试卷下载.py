#!/usr/bin/env python3
# coding:utf-8
import os
import requests
from bs4 import BeautifulSoup
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


def fetch_page_count(url):
    response = requests.get(url)
    response.encoding = "gb2312"
    soup = BeautifulSoup(response.text, "html.parser")
    page = soup.find("ul", class_="pagelist")
    count = int(page.find("strong").string)
    base_url = page.find("a").get("href").rsplit("_", 1)[0]
    return count, base_url


def download_test_papers(page_url, version, save_path, base_url, progress, total_papers):
    response = requests.get(page_url)
    response.encoding = "gb2312"
    soup = BeautifulSoup(response.text, "html.parser")
    test_list = soup.find("ul", class_="c1")
    test_trs = test_list.find_all("tr")

    downloaded = 0

    for tr in test_trs:
        if version in tr.text:
            test_td = tr.find("a").get("href")
            name = tr.find("a").string
            test_url = base_url + test_td
            test_page = requests.get(test_url)
            test_page_soup = BeautifulSoup(test_page.text, "html.parser")
            downurl = test_page_soup.find("ul", class_="downurllist").find("a").get("href")
            download_file(base_url + downurl, os.path.join(save_path, name + ".rar"))

            downloaded += 1
            progress.set(downloaded)
            root.update_idletasks()

            if downloaded >= total_papers:
                return


def download_file(url, path):
    response = requests.get(url)
    with open(path, "wb") as file:
        file.write(response.content)


def start_download():
    subject = subject_var.get()
    grade = grade_var.get()
    version = version_var.get()
    save_path = path_entry.get()
    total_papers = int(papers_var.get())

    if not subject or not grade or not version or not save_path or not total_papers:
        messagebox.showerror("错误", "所有字段都必须填写！")
        return

    url = base_url + subjects[subject] + grades[grade]

    try:
        page_count, page_base_url = fetch_page_count(url)
    except Exception as e:
        messagebox.showerror("错误", f"获取页面数据失败: {e}")
        return

    if not os.path.exists(save_path):
        os.makedirs(save_path)

    try:
        progress.set(0)
        total_progress['maximum'] = total_papers

        for page in range(1, page_count + 1):
            page_url = f"{url}/{page_base_url}_{page}.html"
            download_test_papers(page_url, version, save_path, base_url, progress, total_papers)
            if progress.get() >= total_papers:
                break

        messagebox.showinfo("完成", "所有试卷下载完成！")
    except Exception as e:
        messagebox.showerror("错误", f"下载过程中出错: {e}")


def browse_path():
    path = filedialog.askdirectory()
    if path:
        path_entry.delete(0, tk.END)
        path_entry.insert(0, path)


if __name__ == '__main__':
    base_url = "https://www.shijuan1.com"
    subjects = {
        "语文": "/a/sjyw", "数学": "/a/sjsx", "英语": "/a/sjyy", "物理": "/a/sjwl",
        "化学": "/a/sjhx", "政治": "/a/sjzz", "历史": "/a/sjls", "地理": "/a/sjdl", "生物": "/a/sjsw"
    }
    grades = {
        "一年级": "1", "二年级": "2", "三年级": "3", "四年级": "4", "五年级": "5", "六年级": "6",
        "七年级": "7", "八年级": "8", "九年级": "9", "中考": "zk", "高一": "g1", "高二": "g2", "高三": "g3",
        "高考": "gk"
    }
    versions = ["人教版", "苏教版", "北师大版", "沪教版", "鲁教版", "其他"]

    # 创建主窗口
    root = tk.Tk()
    root.title("试卷下载器")

    # 科目选择
    tk.Label(root, text="科目:").grid(row=0, column=0, padx=10, pady=10)
    subject_var = tk.StringVar()
    subject_combobox = ttk.Combobox(root, textvariable=subject_var, values=list(subjects.keys()))
    subject_combobox.grid(row=0, column=1, padx=10, pady=10)

    # 年级选择
    tk.Label(root, text="年级:").grid(row=1, column=0, padx=10, pady=10)
    grade_var = tk.StringVar()
    grade_combobox = ttk.Combobox(root, textvariable=grade_var, values=list(grades.keys()))
    grade_combobox.grid(row=1, column=1, padx=10, pady=10)

    # 版本信息选择
    tk.Label(root, text="版本信息:").grid(row=2, column=0, padx=10, pady=10)
    version_var = tk.StringVar()
    version_combobox = ttk.Combobox(root, textvariable=version_var, values=versions)
    version_combobox.grid(row=2, column=1, padx=10, pady=10)

    # 保存路径选择
    tk.Label(root, text="保存路径:").grid(row=3, column=0, padx=10, pady=10)
    path_entry = tk.Entry(root)
    path_entry.grid(row=3, column=1, padx=10, pady=10)
    tk.Button(root, text="浏览...", command=browse_path).grid(row=3, column=2, padx=10, pady=10)

    # 下载份数选择
    tk.Label(root, text="下载份数:").grid(row=4, column=0, padx=10, pady=10)
    papers_var = tk.StringVar(value="10")
    papers_entry = tk.Entry(root, textvariable=papers_var)
    papers_entry.grid(row=4, column=1, padx=10, pady=10)

    # 进度条
    progress = tk.IntVar()
    total_progress = ttk.Progressbar(root, variable=progress, maximum=100)
    total_progress.grid(row=5, column=0, columnspan=3, padx=10, pady=10, sticky="ew")

    # 开始下载按钮
    tk.Button(root, text="开始下载", command=start_download).grid(row=6, column=0, columnspan=3, padx=10, pady=20)

    # 运行主循环
    root.mainloop()
