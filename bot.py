import os
import time
import json
import threading
import requests
from datetime import datetime

# ==========================================
# CONFIG - এখানে তোমার তথ্য বসাতে হবে
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
GROUP_ID = os.environ.get("GROUP_ID", "")

API = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?ts="
PERIOD_SECONDS = 30
MAX_HISTORY = 10

# ==========================================
# STATE
# ==========================================
running = False
thread = None
last_issue = None
current_pred = None
recent_predictions = []
history_data = []
win_count = 0
loss_count = 0
loss_streak = 0
last_loss_sig = None
last_pn = None
last_pb = None
period_end_time = 0
next_period_num = "----"
timer_msg_id = None

COLOR_MAP = {
    0: {'color': 'RED+VIOLET', 'emoji': '🔴🟣', 'type': 'SMALL'},
    1: {'color': 'GREEN', 'emoji': '🟢', 'type': 'SMALL'},
    2: {'color': 'RED', 'emoji': '🔴', 'type': 'SMALL'},
    3: {'color': 'GREEN', 'emoji': '🟢', 'type': 'SMALL'},
    4: {'color': 'RED', 'emoji': '🔴', 'type': 'SMALL'},
    5: {'color': 'GREEN+VIOLET', 'emoji': '🟢🟣', 'type': 'BIG'},
    6: {'color': 'RED', 'emoji': '🔴', 'type': 'BIG'},
    7: {'color': 'GREEN', 'emoji': '🟢', 'type': 'BIG'},
    8: {'color': 'RED', 'emoji': '🔴', 'type': 'BIG'},
    9: {'color': 'GREEN', 'emoji': '🟢', 'type': 'BIG'}
}

PATTERNS = {
    'BB': ['S', 68], 'SS': ['B', 68],
    'BBB': ['S', 78], 'SSS': ['B', 78],
    'BBBB': ['S', 82], 'SSSS': ['B', 82],
    'BSB': ['S', 60], 'SBS': ['B', 60],
    'BBS': ['B', 63], 'SSB': ['S', 63],
    'BSS': ['B', 62], 'SBB': ['S', 62],
    'BBSB': ['S', 64], 'SSBS': ['B', 64],
    'BSBS': ['B', 70], 'SBSB': ['S', 70],
    'BSBSB': ['S', 74], 'SBSBS': ['B', 74],
    'BBSS': ['B', 62], 'SSBB': ['S', 62],
    'BBBSS': ['B', 66], 'SSSBB': ['S', 66],
    'BSSBB': ['S', 64], 'SBBSS': ['B', 64],
    'BBBS': ['S', 72], 'SSSB': ['B', 72]
}

# ==========================================
# TELEGRAM HELPERS
# ==========================================
def tg_send(text):
    if not BOT_TOKEN or not GROUP_ID:
        print("[ERR] Token or Group ID missing")
        return None
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": GROUP_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        data = r.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        else:
            print(f"[TG ERR] {data}")
    except Exception as e:
        print(f"[TG EXC] {e}")
    return None

def tg_delete(msg_id):
    if not msg_id:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
        requests.post(url, json={"chat_id": GROUP_ID, "message_id": msg_id}, timeout=10)
    except:
        pass

def tg_get_updates(offset=0):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        r = requests.get(url, params={"offset": offset, "timeout": 5}, timeout=15)
        return r.json()
    except:
        return {"ok": False}

# ==========================================
# ANALYSIS
# ==========================================
def analyze(lst):
    global loss_streak, last_loss_sig, last_pn, last_pb, recent_predictions

    if not lst or len(lst) < 8:
        return None

    rec = [{'n': int(x['number']), 'b': int(x['number']) >= 5} for x in lst[:50]]
    l30 = rec[:30]
    seq = ['B' if r['b'] else 'S' for r in rec]

    bc30 = sum(1 for r in l30 if r['b'])
    sc30 = len(l30) - bc30

    streak = 1
    for i in range(1, len(seq)):
        if seq[i] == seq[0]:
            streak += 1
        else:
            break

    # Pattern match
    ps = None
    pw = 0
    mp = ''
    for k in sorted(PATTERNS.keys(), key=lambda x: -len(x)):
        if len(seq) >= len(k) and ''.join(seq[:len(k)]) == k:
            ps = PATTERNS[k][0]
            pw = PATTERNS[k][1]
            mp = k
            break

    # Short bias (last 10)
    l10 = rec[:10]
    bc10 = sum(1 for r in l10 if r['b'])
    sc10 = len(l10) - bc10
    fb = 0
    if bc10 > sc10 + 3: fb = -3
    elif bc10 > sc10 + 2: fb = -2
    elif bc10 > sc10 + 1: fb = -1
    elif sc10 > bc10 + 3: fb = 3
    elif sc10 > bc10 + 2: fb = 2
    elif sc10 > bc10 + 1: fb = 1

    # Number gap
    nf = {i: 0 for i in range(10)}
    ns = {i: 999 for i in range(10)}
    for r in l30:
        nf[r['n']] += 1
    for i, r in enumerate(rec):
        if ns[r['n']] == 999:
            ns[r['n']] = i

    cluster = {}
    for r in l10:
        cluster[r['n']] = cluster.get(r['n'], 0) + 1

    cold = []
    for i in range(10):
        s = ns[i] * 1.5 - nf[i] * 2
        if cluster.get(i, 0) > 2: s -= 5
        if cluster.get(i, 0) == 1: s += 2
        cold.append({'n': i, 's': s})
    cold.sort(key=lambda x: -x['s'])

    # Anti-repeat
    last5 = [p['big'] for p in recent_predictions[-5:]]
    same_count = 0
    if len(last5) >= 3:
        if last5[-1] == last5[-2] == last5[-3]:
            same_count = 3

    # Decision
    pb = False
    rs = ''
    cf = 68

    if loss_streak >= 1 and last_loss_sig is not None:
        pb = not last_loss_sig
        rs = 'recovery-strong' if loss_streak >= 2 else 'recovery'
        cf = 82 if loss_streak >= 2 else 76
    elif same_count >= 3:
        pb = not last5[-1]
        rs = 'anti-repeat'
        cf = 74
    elif ps and pw >= 76:
        pb = (ps == 'B')
        rs = f'pattern-{mp}'
        cf = pw
    elif ps and pw >= 62:
        agrees = (ps == 'B' and bc10 > sc10) or (ps == 'S' and sc10 > bc10)
        if agrees:
            pb = (ps == 'B')
            rs = 'pat+trend'
            cf = min(pw + 8, 90)
        else:
            pb = bc10 > sc10
            rs = 'trend-override'
            cf = 72
    elif abs(fb) >= 3:
        pb = fb > 0
        rs = 'strong-bias'
        cf = 75
    elif streak >= 6:
        pb = not rec[0]['b']
        rs = 'long-streak'
        cf = 78
    elif abs(fb) >= 2:
        pb = fb > 0
        rs = 'bias'
        cf = 72
    elif streak >= 4:
        pb = not rec[0]['b']
        rs = 'streak-break'
        cf = 72
    else:
        pb = not rec[0]['b']
        rs = 'alternate'
        cf = 67

    # Number
    tt = 'BIG' if pb else 'SMALL'
    vn = [c for c in cold if COLOR_MAP[c['n']]['type'] == tt]
    pnum = vn[0]['n'] if vn else (7 if pb else 2)

    last2 = [p['num'] for p in recent_predictions[-2:]]
    if len(last2) == 2 and last2[0] == pnum and last2[1] == pnum and len(vn) > 1:
        for v in vn:
            if v['n'] != pnum:
                pnum = v['n']
                break

    if pnum == last_pn and pb == last_pb and len(vn) > 1:
        pnum = vn[1]['n']

    cf = max(68, min(90, cf))

    return {
        'big': pb,
        'num': pnum,
        'color': COLOR_MAP[pnum]['color'],
        'emoji': COLOR_MAP[pnum]['emoji'],
        'conf': cf,
        'reason': rs
    }

# ==========================================
# FETCH
# ==========================================
def fetch_history():
    try:
        r = requests.get(API + str(int(time.time() * 1000)), timeout=10)
        data = r.json()
        if data and data.get('data') and data['data'].get('list'):
            return data['data']['list']
    except Exception as e:
        print(f"[FETCH ERR] {e}")
    return None

# ==========================================
# MAIN LOOP
# ==========================================
def main_loop():
    global running, last_issue, current_pred, recent_predictions
    global history_data, win_count, loss_count, loss_streak, last_loss_sig
    global last_pn, last_pb, period_end_time, next_period_num, timer_msg_id

    print("[BOT] Loop started")

    while running:
        try:
            lst = fetch_history()
            if not lst:
                time.sleep(3)
                continue

            latest = lst[0]
            new_issue = latest['issueNumber']
            new_num = int(new_issue)

            if last_issue is not None and last_issue != new_issue:
                # Check previous prediction
                if current_pred:
                    actual = int(latest['number'])
                    actual_big = actual >= 5
                    big_match = (actual_big == current_pred['big'])
                    num_match = (actual == current_pred['num'])
                    jackpot = big_match and num_match
                    won = big_match

                    if won:
                        win_count += 1
                        loss_streak = 0
                        last_loss_sig = None
                    else:
                        loss_count += 1
                        loss_streak += 1
                        last_loss_sig = current_pred['big']

                    history_data.insert(0, {
                        'issue': new_issue[-4:],
                        'pred': 'BIG' if current_pred['big'] else 'SMALL',
                        'pnum': current_pred['num'],
                        'actual': actual,
                        'actual_big': 'BIG' if actual_big else 'SMALL',
                        'won': won,
                        'jackpot': jackpot
                    })
                    history_data = history_data[:MAX_HISTORY]

                    # Send result
                    if jackpot:
                        tg_send(f"👑 <b>JACKPOT!</b>\n\n📅 Period: #{new_issue[-4:]}\n🎯 Predicted: {current_pred['num']}\n✅ Result: {actual}\n\n🏆 <b>PERFECT MATCH!</b>")
                    elif won:
                        tg_send(f"✅ <b>WIN</b>\n\n📅 Period: #{new_issue[-4:]}\n🎯 Predicted: {'BIG' if current_pred['big'] else 'SMALL'} ({current_pred['num']})\n📊 Result: {actual} {'BIG' if actual_big else 'SMALL'}")
                    else:
                        tg_send(f"❌ <b>LOSS</b>\n\n📅 Period: #{new_issue[-4:]}\n🎯 Predicted: {'BIG' if current_pred['big'] else 'SMALL'} ({current_pred['num']})\n📊 Result: {actual} {'BIG' if actual_big else 'SMALL'}")

                last_issue = new_issue
                period_end_time = time.time() + PERIOD_SECONDS

                # New prediction
                pred = analyze(lst)
                if pred:
                    current_pred = pred
                    last_pn = pred['num']
                    last_pb = pred['big']
                    recent_predictions.append({'big': pred['big'], 'num': pred['num']})
                    recent_predictions = recent_predictions[-10:]

                    # Send signal
                    big_txt = '🔵 BIG' if pred['big'] else '🔴 SMALL'
                    tg_send(
                        f"⚡ <b>SABET SIGNAL</b> ⚡\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"📅 Period: <b>#{new_issue[-4:]}</b>\n"
                        f"🎯 Prediction: <b>{big_txt}</b>\n"
                        f"🔢 Number: <b>{pred['num']}</b>\n"
                        f"🎨 Color: <b>{pred['color']}</b> {pred['emoji']}\n"
                        f"📊 Accuracy: <b>{pred['conf']}%</b>\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"⏰ Time: 30s"
                    )

            elif last_issue is None:
                last_issue = new_issue
                period_end_time = time.time() + PERIOD_SECONDS
                pred = analyze(lst)
                if pred:
                    current_pred = pred
                    last_pn = pred['num']
                    last_pb = pred['big']
                    recent_predictions.append({'big': pred['big'], 'num': pred['num']})

            next_period_num = str(new_num + 1)[-4:]

            # Timer update every 5 seconds
            time.sleep(5)

        except Exception as e:
            print(f"[LOOP ERR] {e}")
            time.sleep(5)

    print("[BOT] Loop stopped")

# ==========================================
# COMMAND LISTENER
# ==========================================
def command_listener():
    global running, thread

    offset = 0
    print("[CMD] Listener started")

    while True:
        try:
            updates = tg_get_updates(offset)
            if updates.get('ok') and updates.get('result'):
                for u in updates['result']:
                    offset = u['update_id'] + 1
                    msg = u.get('message')
                    if not msg:
                        continue

                    user_id = msg['from']['id']
                    text = msg.get('text', '').strip()

                    if user_id != ADMIN_ID:
                        continue

                    if text == '/start':
                        if not running:
                            running = True
                            thread = threading.Thread(target=main_loop, daemon=True)
                            thread.start()
                            tg_send("🟢 <b>BOT STARTED</b>\n\nSignals will be sent automatically.")
                        else:
                            tg_send("ℹ️ Bot already running")
                    elif text == '/stop':
                        if running:
                            running = False
                            tg_send("🔴 <b>BOT STOPPED</b>\n\nSignals stopped.")
                        else:
                            tg_send("ℹ️ Bot already stopped")
                    elif text == '/status':
                        total = win_count + loss_count
                        rate = round(win_count * 100 / total, 1) if total > 0 else 0
                        tg_send(
                            f"📊 <b>STATUS</b>\n\n"
                            f"🟢 Running: {'YES' if running else 'NO'}\n"
                            f"✅ Win: {win_count}\n"
                            f"❌ Loss: {loss_count}\n"
                            f"📈 Total: {total}\n"
                            f"🎯 Win Rate: {rate}%"
                        )

            time.sleep(2)
        except Exception as e:
            print(f"[CMD ERR] {e}")
            time.sleep(3)

# ==========================================
# START
# ==========================================
if __name__ == "__main__":
    print("[MAIN] Starting bot...")
    if not BOT_TOKEN:
        print("[ERR] BOT_TOKEN not set")
    elif not GROUP_ID:
        print("[ERR] GROUP_ID not set")
    else:
        # Start command listener in main thread
        command_listener()
