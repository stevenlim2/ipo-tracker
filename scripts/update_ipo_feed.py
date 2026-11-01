#!/usr/bin/env python3
"""Refresh public IPO calendar without touching private subscription records."""
import json, re, urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

SOURCE = "https://www.goldrank.co.kr/ipo-calendar/"
class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables=[]; self.table=None; self.row=None; self.cell=None
    def handle_starttag(self, tag, attrs):
        if tag=="table": self.table=[]
        elif self.table is not None and tag=="tr": self.row=[]
        elif self.row is not None and tag in ("td","th"): self.cell=[]
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ("td","th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split())); self.cell=None
        elif tag=="tr" and self.row is not None:
            if self.row: self.table.append(self.row)
            self.row=None
        elif tag=="table" and self.table is not None:
            self.tables.append(self.table); self.table=None

def main():
    req=urllib.request.Request(SOURCE, headers={"User-Agent":"Mozilla/5.0 (compatible; IPOCalendarSync/1.0)"})
    with urllib.request.urlopen(req,timeout=25) as res:
        html=res.read().decode("utf-8","replace")
    p=TableParser(); p.feed(html)
    entries=[]
    for table in p.tables:
        if not table or not any("청약기간" in c for c in table[0]): continue
        header=table[0]
        def col(word): return next((i for i,c in enumerate(header) if word in c),-1)
        ni,di,bi=col("종목"),col("청약기간"),col("주간사")
        if ni<0 or di<0: continue
        for row in table[1:]:
            if len(row)<=max(ni,di): continue
            name=row[ni].strip()
            dates=re.findall(r"20\d{2}[.-]\d{2}[.-]\d{2}",row[di])
            if not name or len(dates)<2: continue
            start,end=[x.replace(".","-") for x in dates[:2]]
            broker=row[bi] if bi>=0 and len(row)>bi else ""
            entries.append({"name":name,"subscriptionStart":start,"subscriptionEnd":end,"brokers":broker,"type":"스팩" if "스팩" in name else "일반공모주"})
    if len(entries)<5:
        raise RuntimeError(f"Unexpected source format: only {len(entries)} entries; preserving last good feed")
    Path("ipo-feed.json").write_text(json.dumps({"updatedAt":datetime.now(timezone.utc).isoformat(),"source":SOURCE,"ipos":entries},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Saved {len(entries)} IPOs")
if __name__=="__main__": main()
