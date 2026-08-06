#!/usr/bin/env python3
"""
提取 QDjob 日志摘要并推送 Telegram（支持仅今日过滤）
用法：
    python extract_logs.py <log_file> [--today-only] [--date YYYY-MM-DD] [--send] [--bot-token TOKEN] [--chat-id CHAT_ID]
"""
import json
import os
import re
import sys
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import requests
import smtplib
from email.mime.text import MIMEText
from email.header import Header

# 任务列表
TASKS = [
    "每周自动兑换章节卡",
    "签到任务",
    "激励碎片任务",
    "章节卡任务",
    "游戏中心任务",
    "每日抽奖任务",
    "章节卡信息推送"
]

def get_beijing_date():
    """获取当前北京时间日期"""
    utc_now = datetime.utcnow()
    beijing_now = utc_now + timedelta(hours=8)
    return beijing_now.date()

def parse_timestamp(line: str) -> Optional[datetime]:
    match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}', line)
    if match:
        return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
    return None

def extract_username(line: str) -> Optional[str]:
    match = re.search(r'用户\s*\[([^\]]+)\]', line)
    return match.group(1) if match else None

def extract_task_status(line: str) -> Optional[Tuple[str, str, str]]:
    match = re.search(r'任务\[([^\]]+)\]执行(完成|失败)(?::\s*(.*))?', line)
    if match:
        task = match.group(1)
        status = '成功' if match.group(2) == '完成' else '失败'
        reason = match.group(3).strip() if match.group(3) else ''
        return (task, status, reason)
    match2 = re.search(r'任务\[([^\]]+)\]因验证码(?:中断|失败):\s*(.*)', line)
    if match2:
        return (match2.group(1), '失败', f'因验证码: {match2.group(2).strip()}')
    return None

def extract_chapter_info(lines: List[str], start_idx: int) -> Dict[str, str]:
    info = {}
    for i in range(start_idx, len(lines)):
        line = lines[i]
        bal = re.search(r'章节卡余额:\s*([^\s]+)\s*\(共(\d+)张\)', line)
        if bal:
            info['balance'] = bal.group(0).strip()
        exp = re.search(r'最快过期:\s*(.*?)(?=\s*$|, 过期时间)', line)
        if exp:
            full = re.search(r'最快过期:\s*[^,]+,?\s*过期时间:\s*[\d\-:\s]+', line)
            info['expire'] = full.group(0).strip() if full else exp.group(0).strip()
        if 'balance' in info and 'expire' in info:
            break
    return info

def parse_log_file(file_path: str, filter_date=None) -> List[Dict]:
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

            # 如果设置了日期过滤且当前实例不是目标日期，跳过但继续扫描（因为后面可能还有）
            if filter_date is not None and start_time.date() != filter_date:
                # 仍需跳过该实例的所有行
                j = i + 1
                while j < len(lines) and 'QDjob程序启动' not in lines[j]:
                    j += 1
                i = j
                continue

            # 收集该实例的所有行
            instance_lines = []
            j = i
            while j < len(lines):
                if j > i and 'QDjob程序启动' in lines[j]:
                    break
                instance_lines.append(lines[j])
                j += 1
            i = j

            # 提取用户名
            username = None
            for l in instance_lines:
                username = extract_username(l)
                if username:
                    break

            # 解析任务状态
            tasks_status = {task: None for task in TASKS}
            for l in instance_lines:
                status_info = extract_task_status(l)
                if status_info:
                    task, status, reason = status_info
                    if task in tasks_status:
                        tasks_status[task] = {'status': status, 'reason': reason}

            # 章节卡信息
            chapter_balance = ''
            chapter_expire = ''
            for idx, l in enumerate(instance_lines):
                if '任务[章节卡信息推送]执行完成' in l:
                    info = extract_chapter_info(instance_lines, idx)
                    chapter_balance = info.get('balance', '')
                    chapter_expire = info.get('expire', '')
                    break

            # 结束时间
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
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'})
    resp.raise_for_status()

def load_notified_state(state_file):
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            return json.load(f)
    return {}

def save_notified_state(state_file, state):
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)

def send_email_alert(failed_tasks: List[Dict], smtp_host, smtp_port, smtp_user, smtp_password, email_from, email_to):
    """
    failed_tasks: 列表，每个元素包含 'time', 'username', 'task', 'reason'
    """
    if not failed_tasks:
        return

    subject = f"QDjob 验证码失败报警 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    body_lines = ["以下任务因验证码问题执行失败：\n"]
    for item in failed_tasks:
        body_lines.append(f"时间: {item['time']}")
        body_lines.append(f"用户: {item['username']}")
        body_lines.append(f"任务: {item['task']}")
        body_lines.append(f"失败原因: {item['reason']}")
        body_lines.append("")
    body = "\n".join(body_lines)

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = email_from
    msg['To'] = email_to

    try:
        # with smtplib.SMTP(smtp_host, smtp_port) as server:
        with smtplib.SMTP_SSL(smtp_host) as server:
            # server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(email_from, [email_to], msg.as_string())
        print("邮件报警已发送。")
    except Exception as e:
        print(f"邮件发送失败: {e}")
        
def main():
    parser = argparse.ArgumentParser(description='提取 QDjob 日志摘要并推送')
    parser.add_argument('log_file', help='日志文件路径')
    parser.add_argument('--today-only', action='store_true', help='只提取今天（北京时间）的日志')
    parser.add_argument('--date', help='指定日期，格式 YYYY-MM-DD（覆盖 --today-only）')
    parser.add_argument('--send', action='store_true', help='实际发送 Telegram 消息')
    parser.add_argument('--bot-token', help='Telegram Bot Token（发送时必需）')
    parser.add_argument('--chat-id', help='Telegram Chat ID（发送时必需）')
    parser.add_argument('--alert-email', action='store_true', help='检测到验证码失败时发送邮件报警')
    # parser.add_argument('--smtp-host', help='SMTP 服务器地址')
    # parser.add_argument('--smtp-port', type=int, help='SMTP 端口')
    parser.add_argument('--smtp-user', help='SMTP 用户名')
    parser.add_argument('--smtp-password', help='SMTP 密码')
    # parser.add_argument('--email-from', help='发件人邮箱')
    parser.add_argument('--email-to', help='收件人邮箱')
    parser.add_argument('--state-file', default='notified_state.json',
                    help='状态文件路径，用于记录已通知实例')
    args = parser.parse_args()
    smtp_host = 'smtp.163.com'
    smtp_port = 465
    email_from = args.smtp_user

    # 确定过滤日期
    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    elif args.today_only:
        target_date = get_beijing_date()

    instances = parse_log_file(args.log_file, filter_date=target_date)
    if not instances:
        print("未找到任何匹配的日志实例。")
        return
    # ---------- 新增：去重逻辑 ----------
    state_file = args.state_file
    state = load_notified_state(state_file)
    today_str = get_beijing_date().isoformat()  # '2026-08-06'
    notified_times = set(state.get(today_str, []))

    new_instances = []
    for inst in instances:
        time_key = inst['start_time'].strftime('%Y-%m-%d %H:%M:%S')
        if time_key not in notified_times:
            new_instances.append(inst)

    if not new_instances:
        print("所有今日实例已通知，跳过。")
        return

    all_messages = []
    for idx, inst in enumerate(instances, 1):
        all_messages.append(f"--- 运行实例 #{idx} ---\n{format_summary(inst)}")

    combined = "\n\n".join(all_messages)

    # 收集所有验证码失败任务（跨实例）
    captcha_failures = []
    for inst in instances:
        for task, info in inst['tasks'].items():
            if info and info['status'] == '失败' and '验证码' in info['reason']:
                captcha_failures.append({
                    'time': inst['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
                    'username': inst['username'],
                    'task': task,
                    'reason': info['reason']
                })

    # 发送邮件报警（如果启用且存在失败）
    if args.alert_email and captcha_failures:
        if not all([smtp_host, smtp_port, args.smtp_user, args.smtp_password, email_from, args.email_to]):
            print("警告：邮件报警已启用但 SMTP 配置不完整，跳过邮件发送。")
        else:
            send_email_alert(captcha_failures, smtp_host, smtp_port,
                             args.smtp_user, args.smtp_password,
                             email_from, args.email_to)

    
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
        
    # ---------- 更新状态文件（仅在至少一种通知被启用时） ----------
    if args.send or args.alert_email:
        # 将新实例的启动时间加入状态
        if today_str not in state:
            state[today_str] = []
        for inst in new_instances:
            time_key = inst['start_time'].strftime('%Y-%m-%d %H:%M:%S')
            if time_key not in state[today_str]:
                state[today_str].append(time_key)
        save_notified_state(state_file, state)
        print(f"已更新状态文件 {state_file}")

if __name__ == '__main__':
    main()
