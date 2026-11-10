#!/usr/bin/env python3
"""Douyin (抖音) keyword -> top video comments collector via adb/uiautomator (vivo).
Usage: douyin_scrape.py --keyword 猫粮 --max 40 --out ./comments.csv
"""
import argparse, csv, re, subprocess, time, urllib.parse, pathlib
from xml.etree import ElementTree as ET
import os

def adb(serial, *a, timeout=90):
    return subprocess.run(["adb","-s",serial,*a], capture_output=True, text=True, timeout=timeout)

def dump(serial):
    for _ in range(3):
        r = adb(serial,"shell","uiautomator","dump","/sdcard/_d.xml")
        if "dumped" in (r.stdout+r.stderr): break
        time.sleep(0.5)
    return adb(serial,"shell","cat","/sdcard/_d.xml").stdout

def nodes(xml):
    try: root = ET.fromstring(xml)
    except ET.ParseError: return []
    out=[]
    for n in root.iter("node"):
        b=n.get("bounds") or ""
        m=re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
        if not m: continue
        x1,y1,x2,y2=map(int,m.groups())
        out.append({"n":n,"x":(x1+x2)//2,"y":(y1+y2)//2,"x1":x1,"y1":y1,"x2":x2,"y2":y2,
                    "text":(n.get("text") or "").strip(),
                    "cd":n.get("content-desc") or "",
                    "rid":(n.get("resource-id") or "").split("/")[-1],
                    "cls":n.get("class") or ""})
    return out

def find(ns, pred, visible=True):
    for o in ns:
        if pred(o) and (not visible or (o["y1"]>0 and o["y2"]<2256 and o["x2"]>0)):
            return o
    return None

def tap(serial,x,y):
    adb(serial,"shell","input","tap",str(x),str(y))

def rows_from(ns):
    """comment rows: FrameLayout whose content-desc contains 回复"""
    out=[]
    for o in ns:
        if o["cls"]!="android.widget.FrameLayout" or "回复" not in o["cd"]: continue
        rec={"nickname":"","text":"","time":"","region":"","likes":"","replies":""}
        for ch in o["n"].iter("node"):
            t=(ch.get("text") or "").strip(); r=(ch.get("resource-id") or "").split("/")[-1]; cd=ch.get("content-desc") or ""
            if r=="title" and t: rec["nickname"]=rec["nickname"] or t
            elif r=="content" and t: rec["text"]=t
            elif cd.startswith("赞"):
                m=re.match(r"赞(\d+)",cd); rec["likes"]=m.group(1) if m else ""
            elif t.startswith("·"): rec["region"]=t.lstrip("· ").strip()
            elif re.match(r"^(昨天|今天|前天|\d+分钟前|\d+小时前|\d+天前|\d{2}-\d{2})$",t): rec["time"]=t
            elif re.match(r"^展开\d+条回复$",t): rec["replies"]=t
        if rec["text"]: out.append(rec)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--serial",default=os.environ.get("ANDROID_SERIAL"), required=not bool(os.environ.get("ANDROID_SERIAL")))
    ap.add_argument("--keyword",default="猫粮")
    ap.add_argument("--max",type=int,default=40)
    ap.add_argument("--scrolls",type=int,default=20)
    ap.add_argument("--out",default="")
    a=ap.parse_args()
    out=a.out or str(pathlib.Path.home()/f"phone-lab/scrape/douyin_{a.keyword}.csv")
    uri="snssdk1128://search?keyword="+urllib.parse.quote(a.keyword)
    print("[1] open search:", a.keyword)
    adb(a.serial,"shell","am","start","-a","android.intent.action.VIEW","-d",uri); time.sleep(5)
    v=find(nodes(dump(a.serial)), lambda o:o["text"]=="视频")
    if v: print("[2] tap 视频 tab"); tap(a.serial,v["x"],v["y"]); time.sleep(6)
    card=find(nodes(dump(a.serial)), lambda o:o["rid"]=="desc" and len(o["text"])>10)
    if not card: print("!! no video card found"); return
    print("[3] open video:", card["text"][:40]); tap(a.serial,card["x"],card["y"]); time.sleep(6)
    btn=find(nodes(dump(a.serial)), lambda o:"评论" in o["cd"] and "按钮" in o["cd"])
    if not btn: print("!! no comment button"); return
    print("[4] open comments:", btn["cd"]); tap(a.serial,btn["x"],btn["y"]); time.sleep(5)
    exp=find(nodes(dump(a.serial)), lambda o:"放大评论区" in o["cd"])
    if exp:
        print("[4b] expand comment panel"); tap(a.serial,exp["x"],exp["y"]); time.sleep(3)
    seen=set(); allrows=[]
    for i in range(a.scrolls):
        ns=nodes(dump(a.serial)); rs=rows_from(ns); new=0
        for r in rs:
            k=(r["nickname"],r["text"],r["time"])
            if k in seen: continue
            seen.add(k); allrows.append(r); new+=1
        print(f"    scroll {i+1}: visible={len(rs)} new={new} total={len(allrows)}", flush=True)
        if len(allrows)>=a.max: break
        if new==0 and i>1: print("    no new -> stop"); break
        adb(a.serial,"shell","input","swipe","540","1900","540","900","350"); time.sleep(2)
    for r in allrows: r["video"]=card["text"][:80]
    with open(out,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["video","nickname","text","time","region","likes","replies"]); w.writeheader(); w.writerows(allrows)
    print("saved",out,len(allrows),"rows")

if __name__=="__main__": main()
