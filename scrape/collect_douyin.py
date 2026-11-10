#!/usr/bin/env python3
"""Collect Douyin comments from the CURRENTLY OPEN comment panel via adb + uiautomator.
Usage: collect_douyin.py --serial YOUR_ANDROID_SERIAL --max 40 --out ./comments.csv
Each scroll reads the visible XML, parses comment rows, dedupes, and swipes the panel up.
"""
import argparse, re, subprocess, sys, time, csv, json
from xml.etree import ElementTree as ET
import os

def adb(serial, *args, timeout=60):
    return subprocess.run(["adb", "-s", serial, *args], capture_output=True, text=True, timeout=timeout)

def dump(serial, path="/sdcard/dump.xml"):
    adb(serial, "shell", "uiautomator", "dump", path)
    r = adb(serial, "shell", "cat", path)
    return r.stdout

def rid(n): return n.get("resource-id", "").split("/")[-1]

def text_of(n): return (n.get("text") or "").strip()

def parse_rows(xml_text):
    rows = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return rows
    for fr in root.iter("node"):
        if fr.get("class") != "android.widget.FrameLayout":
            continue
        cd = fr.get("content-desc") or ""
        if "回复" not in cd:
            continue
        rec = {"nickname": "", "text": "", "time": "", "region": "", "likes": "", "replies": "", "raw_cd": cd}
        parent_name = None
        for ch in fr.iter("node"):
            r = rid(ch)
            t = text_of(ch)
            chcd = ch.get("content-desc") or ""
            if r == "title" and t:
                rec["nickname"] = rec["nickname"] or t
            elif r == "content" and t:
                rec["text"] = t
            elif chcd.startswith("赞"):
                m = re.match(r"赞(\d+)", chcd)
                if m: rec["likes"] = m.group(1)
            elif t.startswith("·"):
                rec["region"] = t.lstrip("· ").strip()
            elif re.match(r"^(昨天|今天|前天|\d+分钟前|\d+小时前|\d+天前|\d{2}-\d{2})$", t):
                rec["time"] = t
            elif re.match(r"^展开\d+条回复$", t):
                rec["replies"] = t
        if rec["text"]:
            rows.append(rec)
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL"), required=not bool(os.environ.get("ANDROID_SERIAL")))
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--scrolls", type=int, default=15)
    ap.add_argument("--out", default=str(__import__("pathlib").Path.home()/"phone-lab/scrape/douyin_comments.csv"))
    a = ap.parse_args()
    seen, all_rows = set(), []
    for i in range(a.scrolls):
        xml = dump(a.serial)
        rows = parse_rows(xml)
        new = 0
        for r in rows:
            key = (r["nickname"], r["text"], r["time"])
            if key in seen: continue
            seen.add(key); all_rows.append(r); new += 1
        print(f"scroll {i+1}: visible={len(rows)} new={new} total={len(all_rows)}", flush=True)
        if len(all_rows) >= a.max: break
        if new == 0 and i > 2:
            print("no new comments twice; stopping", flush=True); break
        # swipe comment panel up (finger moves up => content scrolls down)
        adb(a.serial, "shell", "input", "swipe", "540", "1900", "540", "900", "350")
        time.sleep(1.5)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["nickname","text","time","region","likes","replies"])
        w.writeheader(); w.writerows([{k: r.get(k,"") for k in w.fieldnames} for r in all_rows])
    print("saved", a.out, len(all_rows), "rows")

if __name__ == "__main__":
    main()
