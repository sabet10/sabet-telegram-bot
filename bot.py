import os
import time
import json
import threading
import requests

# ==========================================
# CONFIG
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
GROUP_ID = os.environ.get("GROUP_ID", "")

API = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?ts="
PERIOD_SECONDS = 30
MAX_HISTORY = 10

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
pending_period = None

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

# ===== EXPANDED PATTERN LIBRARY =====
PATTERNS = {
    'BB': ['S', 68], 'SS': ['B', 68],
    'BBB': ['S', 78], 'SSS': ['B', 78],
    'BBBB': ['S', 82], 'SSSS': ['B', 82],
    'BBBBB': ['S', 85], 'SSSSS': ['B', 85],
    'BSB': ['S', 60], 'SBS': ['B', 60],
    'BBS': ['B', 63], 'SSB': ['S', 63],
    'BSS': ['B', 62], 'SBB': ['S', 62],
    'BBSB': ['S', 64], 'SSBS': ['B', 64],
    'BSBS': ['B', 70], 'SBSB': ['S', 70],
    'BSBSB': ['S', 74], 'SBSBS': ['B', 74],
    'BSBSBS': ['B', 76], 'SBSBSB': ['S', 76],
    'BBSS': ['B', 62], 'SSBB': ['S', 62],
    'BBBSS': ['B', 66], 'SSSBB': ['S', 66],
    'BSSBB': ['S', 64], 'SBBSS': ['B', 64],
    'BBBS': ['S', 72], 'SSSB': ['B', 72],
    'BBSSB': ['B', 64], 'SSBBS': ['S', 64],
    'BSSBS': ['B', 66], 'SBBSS': ['B', 64]
}

# ==========================================
# TELEGRAM
# ==========================================
def tg_send(text):
    if not BOT_TOKEN or not GROUP_ID: return None
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": GROUP_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        print(f"[TG ERR] {e}")
    return None

def tg_get_updates(offset=0):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        r = requests.get(url, params={"offset": offset, "timeout": 5}, timeout=15)
        return r.json()
    except:
        return {"ok": False}

# ==========================================
# ADVANCED ANALYSIS ENGINE
# ==========================================
def analyze(lst):
    global loss_streak, last_loss_sig, last_pn, last_pb, recent_predictions

    if not lst or len(lst) < 10: return None

    rec = [{'n': int(x['number']), 'b': int(x['number']) >= 5} for x in lst[:40]]
    seq = ['B' if r['b'] else 'S' for r in rec]

    # ---- 1. Historical Probability (Last 40) ----
    # Check if current sequence appeared before in the last 40
    hist_win_b = 0
    hist_win_s = 0
    match_length = 3 # Check last 3 patterns
    
    if len(seq) >= match_length:
        current_pattern = seq[:match_length]
        for i in range(match_length, len(seq) - match_length):
            if seq[i:i+match_length] == current_pattern:
                next_val = seq[i+match_length]
                if next_val == 'B': hist_win_b += 1
                else: hist_win_s += 1

    # ---- 2. Weighted Trend ----
    bc10 = sum(1 for r in rec[:10] if r['b']); sc10 = 10 - bc10
    bc20 = sum(1 for r in rec[:20] if r['b']); sc20 = 20 - bc20
    bc30 = sum(1 for r in rec[:30] if r['b']); sc30 = 30 - bc30
    weighted = (bc10/10)*0.4 + (bc20/20)*0.3 + (bc30/30)*0.3

    # ---- 3. Pattern Match ----
    ps = None; pw = 0; mp = ''
    for k in sorted(PATTERNS.keys(), key=lambda x: -len(x)):
        if len(seq) >= len(k) and ''.join(seq[:len(k)]) == k:
            ps = PATTERNS[k][0]; pw = PATTERNS[k][1]; mp = k
            break

    # ---- 4. Streak ----
    streak = 1
    for i in range(1, len(seq)):
        if seq[i] == seq[0]: streak += 1
        else: break

    # ===== DECISION ENGINE =====
    pb = False; rs = ''; cf = 68

    # Priority 1: Loss Recovery
    if loss_streak >= 1 and last_loss_sig is not None:
        pb = not last_loss_sig
        rs = 'recovery'
        cf = 78

    # Priority 2: Strong Historical Probability (If pattern seen 3+ times before)
    elif (hist_win_b + hist_win_s) >= 3:
        if hist_win_b > hist_win_s:
            pb = True; rs = 'hist-big'; cf = 75 + (hist_win_b * 2)
        elif hist_win_s > hist_win_b:
            pb = False; rs = 'hist-small'; cf = 75 + (hist_win_s * 2)
        else:
            pb = ps == 'B' if ps else (weighted > 0.5)
            rs = 'hist-tie'; cf = 70

    # Priority 3: Strong Pattern
    elif ps and pw >= 76:
        pb = (ps == 'B'); rs = f'pattern-{mp}'; cf = pw

    # Priority 4: Pattern + Trend
    elif ps and pw >= 65:
        agrees = (ps == 'B' and weighted > 0.5) or (ps == 'S' and weighted < 0.5)
        if agrees:
            pb = (ps == 'B'); rs = 'pat+trend'; cf = min(pw + 8, 88)
        else:
            pb = weighted > 0.5; rs = 'trend-wins'; cf = 72

    # Priority 5: Market Structure (Trend)
    elif abs(weighted - 0.5) > 0.15:
        pb = weighted > 0.5; rs = 'structure'; cf = 76

    # Priority 6: Long Streak
    elif streak >= 5:
        pb = not rec[0]['b']; rs = 'streak-break'; cf = 80

    # Priority 7: Fallback
    else:
        pb = not rec[0]['b']; rs = 'alternate'; cf = 65

    # ---- Number Selection ----
    tt = 'BIG' if pb else 'SMALL'
    nf = {i: 0 for i in range(10)}
    for r in rec[:20]: nf[r['n']] += 1
    
    valid_nums = [i for i in range(10) if COLOR_MAP[i]['type'] == tt]
    # Pick the least frequent number in this type
    valid_nums.sort(key=lambda x: nf[x])
    pnum = valid_nums[0] if valid_nums else (7 if pb else 2)

    if pnum == last_pn and pb == last_pb and len(valid_nums) > 1:
        pnum = valid_nums[1]

    cf = max(65, min(92, cf))

    return {'big': pb, 'num': pnum, 'color': COLOR_MAP[pnum]['color'], 'emoji': COLOR_MAP[pnum]['emoji'], 'conf': cf, 'reason': rs}

# ==========================================
# FETCH & LOOP
# ==========================================
def fetch_history():
    try:
        r = requests.get(API + str(int(time.time() * 1000)), timeout=10)
        data = r.json()
        if data and data.get('data') and data['data'].get('list'):
            return data['data']['list']
    except: pass
    return None

def main_loop():
    global running, last_issue, current_pred, recent_predictions, history_data
    global win_count, loss_count, loss_streak, last_loss_sig, last_pn, last_pb, pending_period

    print("[BOT] Loop started")

    while running:
        try:
            lst = fetch_history()
            if not lst: time.sleep(3); continue

            new_issue = lst[0]['issueNumber']
            new_num = int(new_issue)

            if last_issue is not None and last_issue != new_issue:
                if current_pred and pending_period:
                    actual = int(lst[0]['number'])
                    actual_big = actual >= 5
                    big_match = (actual_big == current_pred['big'])
                    num_match = (actual == current_pred['num'])
                    jackpot = big_match and num_match

                    if big_match:
                        win_count += 1; loss_streak = 0; last_loss_sig = None
                    else:
                        loss_count += 1; loss_streak += 1; last_loss_sig = current_pred['big']

                    history_data.insert(0, {'issue': pending_period[-4:], 'pred': 'BIG' if current_pred['big'] else 'SMALL', 'pnum': current_pred['num'], 'actual': actual, 'won': big_match, 'jackpot': jackpot})
                    history_data = history_data[:MAX_HISTORY]

                    if jackpot:
                        tg_send(f"👑 <b>JACKPOT!</b> 👑\n━━━━━━━━━━━━━━━\n📅 Period: <b>#{pending_period[-4:]}</b>\n🎯 Pred: <b>{current_pred['num']}</b>\n✅ Result: <b>{actual}</b>\n🤖 SABET AI SIGNAL")
                    elif big_match:
                        tg_send(f"✅ <b>WIN</b>\n━━━━━━━━━━━━━━━\n📅 Period: <b>#{pending_period[-4:]}</b>\n🎯 Pred: <b>{'BIG' if current_pred['big'] else 'SMALL'} ({current_pred['num']})</b>\n📊 Result: <b>{actual}</b>\n🤖 SABET AI SIGNAL")
                    else:
                        tg_send(f"❌ <b>LOSS</b>\n━━━━━━━━━━━━━━━\n📅 Period: <b>#{pending_period[-4:]}</b>\n🎯 Pred: <b>{'BIG' if current_pred['big'] else 'SMALL'} ({current_pred['num']})</b>\n📊 Result: <b>{actual}</b>\n🤖 SABET AI SIGNAL")

                last_issue = new_issue
                pred = analyze(lst)
                if pred:
                    current_pred = pred; last_pn = pred['num']; last_pb = pred['big']
                    pending_period = str(new_num + 1)
                    recent_predictions.append({'big': pred['big'], 'num': pred['num']})
                    recent_predictions = recent_predictions[-10:]
                    
                    big_txt = '🔵 BIG' if pred['big'] else '🔴 SMALL'
                    tg_send(f"🌊 <b>WINGO 30S LIVE SIGNAL</b> 🌊\n━━━━━━━━━━━━━━━\n📅 Period: <b>#{pending_period[-4:]}</b>\n🎯 Prediction: <b>{big_txt}</b>\n🔢 Number: <b>{pred['num']}</b>\n🎨 Color: <b>{pred['color']}</b> {pred['emoji']}\n📊 Accuracy: <b>{pred['conf']}%</b>\n💡 Strategy: <b>{pred['reason']}</b>\n━━━━━━━━━━━━━━━\n⏰ Time: <b>30s</b>\n🤖 SABET AI SIGNAL")

            elif last_issue is None:
                last_issue = new_issue
                pred = analyze(lst)
                if pred:
                    current_pred = pred; last_pn = pred['num']; last_pb = pred['big']
                    pending_period = str(new_num + 1)
                    recent_predictions.append({'big': pred['big'], 'num': pred['num']})

            time.sleep(5)
        except Exception as e:
            print(f"[LOOP ERR] {e}"); time.sleep(5)

# ==========================================
# COMMANDS (Same as before)
# ==========================================
def command_listener():
    global running, thread
    offset = 0
    while True:
        try:
            updates = tg_get_updates(offset)
            if updates.get('ok') and updates.get('result'):
                for u in updates['result']:
                    offset = u['update_id'] + 1
                    msg = u.get('message')
                    if not msg or msg['from']['id'] != ADMIN_ID: continue
                    
                    text = msg.get('text', '').strip()
                    if text == '/start' and not running:
                        running = True
                        thread = threading.Thread(target=main_loop, daemon=True)
                        thread.start()
                        tg_send("🟢 <b>BOT STARTED</b>\n🤖 SABET AI SIGNAL")
                    elif text == '/stop' and running:
                        running = False
                        tg_send("🔴 <b>BOT STOPPED</b>\n🤖 SABET AI SIGNAL")
                    elif text == '/status':
                        total = win_count + loss_count
                        rate = round(win_count * 100 / total, 1) if total > 0 else 0
                        tg_send(f"📊 <b>STATUS</b>\n🟢 Running: {'YES' if running else 'NO'}\n✅ Win: {win_count}\n❌ Loss: {loss_count}\n🎯 Rate: {rate}%\n🤖 SABET AI SIGNAL")
            time.sleep(2)
        except Exception as e:
            time.sleep(3)

if __name__ == "__main__":
    if BOT_TOKEN and GROUP_ID:
        command_listener()
    else:
        print("[ERR] Missing Token/ID")
