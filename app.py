# 1. 低基期乖離控制 (防追高，站上月線且距離月線不超過 8%)
bias_ma20 = (curr_p - ma20) / ma20
if 0 < bias_ma20 <= 0.08:
    score += 25
    features.append("低基期緊貼月線起漲")
elif bias_ma20 > 0.08:
    score += 10
    features.append("已脫離成本區(注意乖離)")

# 2. 量能點火與 KD 低檔金叉
vol_ma20 = hist['Volume'].rolling(20).mean().iloc[-1]
is_vol_surge = hist['Volume'].iloc[-1] >= (vol_ma20 * 1.5)
if k_val > d_val and k_val < 65:  # 專抓中低檔發動，避開高檔鈍化
    if is_vol_surge:
        score += 25
        features.append("帶量低檔金叉(主力表態)")
    else:
        score += 15
        features.append("低檔金叉(量能尚溫)")

# 3. 獲利基本面 (兼顧高毛利與轉機)
if gm and gm >= 0.35:
    score += 25
    features.append(f"超高毛利({round(gm*100, 1)}%)")
elif gm and gm >= 0.20:
    score += 15
    features.append(f"穩健毛利({round(gm*100, 1)}%)")

# 4. 型態爆發加分 (Bonus 直接疊加到總分)
pat, target, stop = detect_pattern(hist)
if "均線糾結" in pat or "破底翻" in pat:
    score += 15
    features.append(f"🔥極佳起漲型態:{pat}(+15分)")
elif pat != "":
    score += 10
    features.append(f"🔥動能突破:{pat}(+10分)")
    
