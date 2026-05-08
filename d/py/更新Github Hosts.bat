@echo off
chcp 65001 >nul
title 一键更新GitHub最新Hosts（自动拉取IP）
echo ==============================
echo 正在自动获取最新GitHub IP...
echo ==============================

:: 1. 下载最新hosts（来自GitHub520社区维护的最新IP）
powershell -Command "(New-Object Net.WebClient).DownloadFile('https://raw.githubusercontent.com/521xueweihan/GitHub520/main/hosts', '%temp%\github_latest_hosts.txt')"

:: 2. 清理旧的GitHub相关hosts（避免重复）
findstr /v "# GitHub Hosts" C:\Windows\System32\drivers\etc\hosts > C:\Windows\System32\drivers\etc\hosts.tmp

:: 3. 追加最新hosts到系统hosts
type C:\Windows\System32\drivers\etc\hosts.tmp > C:\Windows\System32\drivers\etc\hosts
type %temp%\github_latest_hosts.txt >> C:\Windows\System32\drivers\etc\hosts

:: 4. 刷新DNS
ipconfig /flushdns >nul

:: 5. 清理临时文件
del %temp%\github_latest_hosts.txt
del C:\Windows\System32\drivers\etc\hosts.tmp

echo.
echo ✅ 完成！已自动替换为最新GitHub IP并刷新DNS
echo 现在直接打开GitHub即可，以后抽风再跑一次
pause >nul