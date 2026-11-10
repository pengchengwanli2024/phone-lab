#!/usr/bin/env python3
"""Douyin: aggregate comments from the top N videos of a keyword search.
Douyin forces login after ~10 comments per video, so we take the public slice of each video.
Usage: douyin_multi.py --keyword 猫粮 --videos 5 --out ./comments.csv
"""
import argparse, csv, re, subprocess, time, urllib.parse, pathlib
from xml.etree import ElementTree as ET
import os

def adb(s,*a,t=90): return subprocess.run(["adb","-s",s,*a],capture_output=True,text=True,timeout=t)
def dump(s):
    for _ in range(3):
        r=adb(s,"shell","uiautomator","dump","/sdcard/_d.xml")
        if "dumped" in r.stdout+r.stderr: break
        time.sleep(0.4)
    return adb(s,"shell","cat","/sdcard/_d.xml").stdout
def nodes(xml):
    try: root=ET.fromstring(xml)
    except ET.ParseError: return []
    out=[]
    for n in root.iter("node"):
        m=re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds") or "")
        if not m: continue
        x1,y1,x2,y2=map(int,m.groups())
        out.append({"n":n,"x":(x1+x2)//2,"y":(y1+y2)//2,"y1":y1,"y2":y2,
                    "text":(n.get("text") or "").strip(),"cd":n.get("content-desc") or "",
                    "rid":(n.get("resource-id") or "").split("/")[-1],"cls":n.get("class") or ""})
    return out
def find(ns,pred):
    for o in ns:
        if pred(o) and o["y1"]>0 and o["y2"]<2256: return o
    return None
def tap(s,x,y): adb(s,"shell","input","tap",str(x),str(y))
def rows(ns):
    out=[]
    for o in ns:
        if o["cls"]!="android.widget.FrameLayout" or "回复" not in o["cd"]: continue
        r={"nickname":"","text":"","time":"","region":"","likes":"","replies":""}
        for ch in o["n"].iter("node"):
            t=(ch.get("text") or "").strip(); rid=(ch.get("resource-id") or "").split("/")[-1]; cd=ch.get("content-desc") or ""
            if rid=="title" and t: r["nickname"]=r["nickname"] or t
            elif rid=="content" and t: r["text"]=t
            elif cd.startswith("赞"):
                m=re.match(r"赞(\d+)",cd); r["likes"]=m.group(1) if m else ""
            elif t.startswith("·"): r["region"]=t.lstrip("· ").strip()
            elif re.match(r"^(昨天|今天|前天|\d+分钟前|\d+小时前|\d+天前|\d{2}-\d{2})$",t): r["time"]=t
            elif re.match(r"^展开\d+条回复$",t): r["replies"]=t
        if r["text"]: out.append(r)
    return out
def login_wall(ns): return any("登录看更多" in (o["text"]+o["cd"]) for o in ns)
def ensure_results(s, keyword):
    for _ in range(5):
        ns=nodes(dump(s))
        if any(o["text"]=="视频" for o in ns) and any(o["rid"]=="desc" and len(o["text"])>10 for o in ns):
            return True
        adb(s,"shell","input","keyevent","KEYCODE_BACK"); time.sleep(1.5)
    adb(s,"shell","am","start","-a","android.intent.action.VIEW","-d",
        "snssdk1128://search?keyword="+urllib.parse.quote(keyword)); time.sleep(5)
    v=find(nodes(dump(s)), lambda o:o["text"]=="视频")
    if v: tap(s,v["x"],v["y"]); time.sleep(5)
    return True

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--serial",default=os.environ.get("ANDROID_SERIAL"), required=not bool(os.environ.get("ANDROID_SERIAL"))); ap.add_argument("--keyword",default="猫粮")
    ap.add_argument("--videos",type=int,default=5); ap.add_argument("--out",default="")
    a=ap.parse_args(); out=a.out or str(pathlib.Path.home()/f"phone-lab/scrape/douyin_{a.keyword}.csv")
    adb(a.serial,"shell","am","start","-a","android.intent.action.VIEW","-d",
        "snssdk1128://search?keyword="+urllib.parse.quote(a.keyword)); time.sleep(5)
    v=find(nodes(dump(a.serial)), lambda o:o["text"]=="视频")
    if v: tap(a.serial,v["x"],v["y"]); time.sleep(6)
    allrows=[]; seen=set()
    for vi in range(a.videos):
        ensure_results(a.serial, a.keyword)
        ns=nodes(dump(a.serial))
        cards=[o for o in ns if o["rid"]=="desc" and len(o["text"])>10 and o["y1"]>400]
        cards=cards[vi % len(cards):] + cards[:vi % len(cards)] if cards else []
        if not cards: print(f"[video {vi+1}] no cards, stop"); break
        card=cards[0]
        title=card["text"][:80]
        print(f"[video {vi+1}] {title[:40]}")
        tap(a.serial,card["x"],card["y"]); time.sleep(6)
        btn=find(nodes(dump(a.serial)), lambda o:"评论" in o["cd"] and "按钮" in o["cd"])
        if not btn: print("   no comment button; back out"); adb(a.serial,"shell","input","keyevent","KEYCODE_BACK"); time.sleep(2); continue
        tap(a.serial,btn["x"],btn["y"]); time.sleep(5)
        exp=find(nodes(dump(a.serial)), lambda o:"放大评论区" in o["cd"])
        if exp: tap(a.serial,exp["x"],exp["y"]); time.sleep(3)
        got=0
        for sc in range(12):
            nsn=nodes(dump(a.serial))
            if login_wall(nsn):
                print(f"   login wall after {got} comments");
                x=find(nsn, lambda o:o["cd"]=="关闭");
                if x: tap(a.serial,x["x"],x["y"])
                time.sleep(1); break
            rs=rows(nsn); new=0
            for r in rs:
                k=(r["nickname"],r["text"],r["time"])
                if k in seen: continue
                seen.add(k); r["video"]=title; allrows.append(r); new+=1; got+=1
            if new==0 and sc>0:
                adb(a.serial,"shell","input","swipe","540","1800","540","1000","350")
            else:
                adb(a.serial,"shell","input","swipe","540","1800","540","1000","350")
            time.sleep(1.5)
        print(f"   collected {got} (total {len(allrows)})")
        # leave video + comments, come back to the video results grid
        ensure_results(a.serial, a.keyword)
    with open(out,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["video","nickname","text","time","region","likes","replies"]); w.writeheader(); w.writerows(allrows)
    print("saved",out,len(allrows),"rows")

if __name__=="__main__": main()
