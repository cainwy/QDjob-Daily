#!/usr/bin/env python3
"""
提取 QDjob 日志摘要并推送 Telegram
用法：
    python extract_logs.py <log_file> [--send] [--bot-token TOKEN] [--chat-id CHAT_ID]
"""

import re
import sys
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import requests

# 任务列表（包含周日可选任务）
TASKS = [
    "每周自动兑换章节卡",   # 仅周日出现
    "签到任务",
    "激励碎片任务",
    "章节卡任务",
    "游戏中心任务",
    "每日抽奖任务",
    "章节卡信息推送"
]

def parse_timestamp(line: str) -> Optional[datetime]:
    """从日志行提取时间戳（精确到秒）"""
    match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}', line)
    if match:
        return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
    return None

def extract_username(line: str) -> Optional[str]:
    """提取用户[xxx]或用户 [xxx] 中的用户名"""
    match = re.search(r'用户\s*\[([^\]]+)\]', line)
    return match.group(1) if match else None

def extract_task_status(line: str) -> Optional[Tuple[str, str, str]]:
    """
    提取任务的最终状态（成功/失败及原因）
    返回 (任务名, 状态, 原因)
    """
    # 匹配 "任务[xxx]执行完成" 或 "任务[xxx]执行失败"
    match = re.search(r'任务\[([^\]]+)\]执行(完成|失败)(?::\s*(.*))?', line)
    if match:
        task = match.group(1)
        status = '成功' if match.group(2) == '完成' else '失败'
        reason = match.group(3).strip() if match.group(3) else ''
        return (task, status, reason)
    # 匹配因验证码中断/失败
    match2 = re.search(r'任务\[([^\]]+)\]因验证码(?:中断|失败):\s*(.*)', line)
    if match2:
        return (match2.group(1), '失败', f'因验证码: {match2.group(2).strip()}')
    return None

def extract_chapter_info(lines: List[str], start_idx: int) -> Dict[str, str]:
    """从指定行开始查找章节卡余额和最快过期信息"""
    info = {}
    for i in range(start_idx, len(lines)):
        line = lines[i]
        bal = re.search(r'章节卡余额:\s*([^\s]+)\s*\(共(\d+)张\)', line)
        if bal:
            info['balance'] = bal.group(0).strip()
        exp = re.search(r'最快过期:\s*(.*?)(?=\s*$|, 过期时间)', line)
        if exp:
            # 尝试获取完整行
            full = re.search(r'最快过期:\s*[^,]+,?\s*过期时间:\s*[\d\-:\s]+', line)
            info['expire'] = full.group(0).strip() if full else exp.group(0).strip()
        if 'balance' in info and 'expire' in info:
            break
    return info

def parse_log_file(file_path: str) -> List[Dict]:
    """解析日志文件，返回每个运行实例的摘要列表"""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    instances = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if 'QDjob程序启动' in line:
            start_time = parse_timestamp(line)
            if not start_time:
                i += 1
                continue

            # 收集该实例的所有行（直到下一个启动或文件末尾）
            instance_lines = []
            j = i
            while j < len(lines):
                if j > i and 'QDjob程序启动' in lines[j]:
                    break
                instance_lines.append(lines[j])
                j += 1
            i = j   # 移到下一个启动行

            # 提取用户名（从所有行中查找第一个匹配）
            username = None
            for l in instance_lines:
                username = extract_username(l)
                if username:
                    break

            # 解析任务状态（只保留每个任务的最终状态，即最后一次出现）
            tasks_status = {task: None for task in TASKS}
            for l in instance_lines:
                status_info = extract_task_status(l)
                if status_info:
                    task, status, reason = status_info
                    if task in tasks_status:
                        tasks_status[task] = {'status': status, 'reason': reason}

            # 查找章节卡信息（在"章节卡信息推送"完成后）
            chapter_balance = ''
            chapter_expire = ''
            for idx, l in enumerate(instance_lines):
                if '任务[章节卡信息推送]执行完成' in l:
                    info = extract_chapter_info(instance_lines, idx)
                    chapter_balance = info.get('balance', '')
                    chapter_expire = info.get('expire', '')
                    break

            # 计算结束时间（从后往前找第一条有时间戳的行）
            end_time = None
            for l in reversed(instance_lines):
                ts = parse_timestamp(l)
                if ts:
                    end_time = ts
                    break
            if end_time is None:
                end_time = start_time

            duration = end_time - start_time

            summary = {
                'start_time': start_time,
                'username': username or 'unknown',
                'tasks': tasks_status,
                'chapter_balance': chapter_balance,
                'chapter_expire': chapter_expire,
                'end_time': end_time,
                'duration': duration
            }
            instances.append(summary)
        else:
            i += 1

    return instances

def format_summary(summary: Dict) -> str:
    """格式化单个运行实例的摘要"""
    start = summary['start_time'].strftime('%Y-%m-%d %H:%M:%S')
    duration_sec = summary['duration'].total_seconds()
    hours, rem = divmod(duration_sec, 3600)
    minutes, seconds = divmod(rem, 60)
    duration_str = f"{int(hours)}h{int(minutes):02d}m{int(seconds):02d}s" if hours else f"{int(minutes)}m{int(seconds):02d}s"

    lines = [
        f"📅 运行时间: {start}",
        f"👤 用户: {summary['username']}",
        f"⏱️ 总耗时: {duration_str}",
        "📋 任务执行结果:"
    ]

    for task in TASKS:
        info = summary['tasks'].get(task)
        if info is None:
            lines.append(f"  • {task}: ⚪ 未执行")
        elif info['status'] == '成功':
            lines.append(f"  • {task}: ✅ 成功")
        else:
            reason = info['reason'] if info['reason'] else '未知原因'
            lines.append(f"  • {task}: ❌ 失败 ({reason})")

    if summary['chapter_balance'] or summary['chapter_expire']:
        lines.append("📚 章节卡信息:")
        if summary['chapter_balance']:
            lines.append(f"  {summary['chapter_balance']}")
        if summary['chapter_expire']:
            lines.append(f"  {summary['chapter_expire']}")
    else:
        lines.append("📚 章节卡信息: 无")

    return "\n".join(lines)

def send_telegram(text: str, bot_token: str, chat_id: str):
    """通过 Telegram Bot 发送消息"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'})
    resp.raise_for_status()

def main():
    parser = argparse.ArgumentParser(description='提取 QDjob 日志摘要并推送')
    parser.add_argument('log_file', help='日志文件路径')
    parser.add_argument('--send', action='store_true', help='实际发送 Telegram 消息')
    parser.add_argument('--bot-token', help='Telegram Bot Token（发送时必需）')
    parser.add_argument('--chat-id', help='Telegram Chat ID（发送时必需）')
    args = parser.parse_args()

    instances = parse_log_file(args.log_file)
    if not instances:
        print("未找到任何运行实例。")
        return

    all_messages = []
    for idx, inst in enumerate(instances, 1):
        all_messages.append(f"--- 运行实例 #{idx} ---\n{format_summary(inst)}")

    combined = "\n\n".join(all_messages)

    if args.send:
        if not args.bot_token or not args.chat_id:
            print("错误：发送消息需要提供 --bot-token 和 --chat-id")
            sys.exit(1)
        try:
            send_telegram(combined, args.bot_token, args.chat_id)
            print("消息已发送成功。")
        except Exception as e:
            print(f"发送失败: {e}")
            sys.exit(1)
    else:
        print(combined)

if __name__ == '__main__':
    main()
