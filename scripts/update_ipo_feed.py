#!/usr/bin/env python3
"""Refresh public IPO calendar without touching private subscription records."""
import json, re, urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

SOURCE = "https://www.goldrank.co.kr/ipo-calendar/"
SOURCE_38_SUB = "https://www.38.co.kr/html/fund/index.htm?o=k"
SOURCE_38_LIST = "https://www.38.co.kr/html/fund/index.htm?o=nw"
LISTING_SOURCE = "https://ipo.aippopick.shop/"
KIND_SOURCE = "https://kind.krx.co.kr/listinvstg/pubofrprogcom.do?method=searchPubofrProgComMain"
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

def listing_dates():
    """Read the published listing-date column, never infer from subscription dates."""
    req=urllib.request.Request(LISTING_SOURCE,headers={"User-Agent":"Mozilla/5.0 (compatible; IPOCalendarSync/1.0)"})
    with urllib.request.urlopen(req,timeout=25) as res:
        html=res.read().decode("utf-8","replace")
    p=TableParser(); p.feed(html)
    found={}
    for table in p.tables:
        if not table: continue
        headers=table[0]
        name_idx=next((i for i,c in enumerate(headers) if "종목" in c),-1)
        date_idx=next((i for i,c in enumerate(headers) if "상장일" in c),-1)
        if name_idx<0 or date_idx<0: continue
        for row in table[1:]:
            if len(row)<=max(name_idx,date_idx): continue
            name=re.sub(r"\s+","",row[name_idx])
            raw=row[date_idx]
            m=re.search(r"(20\d{2})[년.\-/ ]+([01]?\d)[월.\-/ ]+([0-3]?\d)",raw)
            if m and name:
                year,month,day=map(int,m.groups())
                try:
                    date=f"{year:04d}-{month:02d}-{day:02d}"
                    datetime.fromisoformat(date)
                    found[name]=date
                except ValueError: pass
    if len(found)<1:
        raise RuntimeError(f"Listing source format changed: only {len(found)} dated rows")
    return found

def kind_listing_dates():
    """Use KRX KIND's official IPO company table as the primary listing-date source."""
    req=urllib.request.Request(KIND_SOURCE,headers={"User-Agent":"Mozilla/5.0 (compatible; IPOCalendarSync/1.0)"})
    with urllib.request.urlopen(req,timeout=30) as res:
        html=res.read().decode("utf-8","replace")
    p=TableParser(); p.feed(html)
    found={}
    for table in p.tables:
        if not table: continue
        headers=table[0]
        name_idx=next((i for i,c in enumerate(headers) if "회사명" in c or c.strip()=="기업명"),-1)
        date_idx=next((i for i,c in enumerate(headers) if "상장예정일" in c),-1)
        if name_idx<0 or date_idx<0: continue
        for row in table[1:]:
            if len(row)<=max(name_idx,date_idx): continue
            name=re.sub(r"\s+","",row[name_idx])
            raw=row[date_idx]
            m=re.search(r"(20\d{2})[-./년 ]+([01]?\d)[-./월 ]+([0-3]?\d)",raw)
            if not m or not name: continue
            try:
                y,mo,d=map(int,m.groups())
                date=f"{y:04d}-{mo:02d}-{d:02d}"
                datetime.fromisoformat(date)
                found[name]=date
            except ValueError:
                continue
    if not found:
        raise RuntimeError("KIND page did not yield any official IPO listing dates")
    return found


def tables38(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept-Language":"ko-KR"})
    with urllib.request.urlopen(req,timeout=30) as res:
        raw=res.read()
    for enc in ("utf-8","cp949","euc-kr"):
        try:
            html=raw.decode(enc)
            if "종목명" in html or "기업명" in html:
                p=TableParser();p.feed(html);return p.tables
        except UnicodeError:pass
    raise RuntimeError("38 source unreadable")

def normalized(name):
    return re.sub(r"\s+|\(구\.[^)]*\)|\(유가\)","",name)

def feed38():
    result=[]
    for table in tables38(SOURCE_38_SUB):
        if not table:continue
        head=table[0]
        ni=next((i for i,c in enumerate(head) if "종목명" in c),-1)
        di=next((i for i,c in enumerate(head) if "공모주일정" in c),-1)
        bi=next((i for i,c in enumerate(head) if "주간사" in c),-1)
        if ni<0 or di<0:continue
        for row in table[1:]:
            if len(row)<=max(ni,di):continue
            m=re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})\s*[~～-]\s*(?:(20\d{2})[./-])?(\d{1,2})[./-](\d{1,2})",row[di])
            if not m:continue
            y,mo,day,ey,em,ed=m.groups()
            start=f"{int(y):04d}-{int(mo):02d}-{int(day):02d}"
            end=f"{int(ey or y):04d}-{int(em):02d}-{int(ed):02d}"
            try:datetime.fromisoformat(start);datetime.fromisoformat(end)
            except ValueError:continue
            name=row[ni].strip()
            if name:result.append({"name":name,"subscriptionStart":start,"subscriptionEnd":end,"brokers":row[bi] if bi>=0 and len(row)>bi else "","type":"스팩" if "스팩" in name else "일반공모주"})
    if not result:raise RuntimeError("38 subscription table unavailable")
    if max(x["subscriptionEnd"] for x in result)<(datetime.now(timezone.utc)-timedelta(days=45)).date().isoformat():
        raise RuntimeError("38 subscription table stale")
    return result

def listings38():
    result={}
    for table in tables38(SOURCE_38_LIST):
        if not table:continue
        head=table[0]
        ni=next((i for i,c in enumerate(head) if "기업명" in c),-1)
        di=next((i for i,c in enumerate(head) if "신규상장일" in c),-1)
        if ni<0 or di<0:continue
        for row in table[1:]:
            if len(row)<=max(ni,di):continue
            m=re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})",row[di])
            if not m:continue
            y,mo,day=map(int,m.groups())
            date=f"{y:04d}-{mo:02d}-{day:02d}"
            try:datetime.fromisoformat(date)
            except ValueError:continue
            result[normalized(row[ni])]=date
    if not result:raise RuntimeError("38 listing table unavailable")
    if max(result.values())<(datetime.now(timezone.utc)-timedelta(days=45)).date().isoformat():
        raise RuntimeError("38 listing table stale")
    return result

def goldrank_feed():
    req=urllib.request.Request(SOURCE,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=25) as res:
        html=res.read().decode("utf-8","replace")
    p=TableParser();p.feed(html)
    entries=[]
    for table in p.tables:
        if not table or not any("청약기간" in c for c in table[0]):continue
        header=table[0]
        def col(word):return next((i for i,c in enumerate(header) if word in c),-1)
        ni,di,bi=col("종목"),col("청약기간"),col("주간사")
        if ni<0 or di<0:continue
        for row in table[1:]:
            if len(row)<=max(ni,di):continue
            name=row[ni].strip()
            dates=re.findall(r"20\d{2}[.-]\d{2}[.-]\d{2}",row[di])
            if not name or len(dates)<2:continue
            start,end=[x.replace(".","-") for x in dates[:2]]
            entries.append({"name":name,"subscriptionStart":start,"subscriptionEnd":end,"brokers":row[bi] if bi>=0 and len(row)>bi else "","type":"스팩" if "스팩" in name else "일반공모주"})
    if len(entries)<5:raise RuntimeError("Goldrank returned too few IPOs")
    return entries


FINUTS_SOURCE = "https://www.finuts.co.kr/html/ipo/"
class FinutsLinks(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids=set()
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            m=re.search(r"ipoView\\.php\\?ipo_sn=(\\d+)",dict(attrs).get("href",""))
            if m:self.ids.add(m.group(1))

def finuts_dates(entries):
    from concurrent.futures import ThreadPoolExecutor
    from html import unescape
    req=urllib.request.Request(FINUTS_SOURCE,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=20) as res:html=res.read().decode("utf-8","replace")
    links=FinutsLinks();links.feed(html)
    if not links.ids:raise RuntimeError("Finuts detail links not found")
    names={normalized(x["name"]):x for x in entries}
    def fetch(sn):
        url=FINUTS_SOURCE+"ipoView.php?ipo_sn="+sn
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=12) as res:raw=res.read()
        page=raw.decode("utf-8","replace")
        title=re.search(r"<title[^>]*>(.*?)</title>",page,re.I|re.S)
        if not title:return None
        heading=normalized(unescape(re.sub(r"<[^>]+>"," ",title.group(1))))
        name=next((n for n in names if n and n in heading),None)
        if not name:return None
        plain=" ".join(unescape(re.sub(r"<[^>]+>"," ",page)).split())
        m=re.search(r"상장일\\s*(20\\d{2})\\s*[.년/-]\\s*(\\d{1,2})\\s*[.월/-]\\s*(\\d{1,2})",plain)
        if not m:return None
        y,mo,d=map(int,m.groups());date=f"{y:04d}-{mo:02d}-{d:02d}"
        try:datetime.fromisoformat(date)
        except ValueError:return None
        return name,date
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda sn: safe_finuts_fetch(fetch,sn),list(links.ids)[:120]))
    found=dict(x for x in results if x)
    if not found:raise RuntimeError("No matching Finuts listing dates")
    return found

def safe_finuts_fetch(fn,sn):
    try:return fn(sn)
    except Exception:return None

def main():
    # Never make the backup source a mandatory prerequisite to the primary source.
    source_used=SOURCE_38_SUB
    try:
        entries=feed38()
        print(f"38 subscription records: {len(entries)}")
    except Exception as exc:
        print(f"38 subscriptions unavailable, trying Goldrank: {exc}")
        try:
            entries=goldrank_feed()
            source_used=SOURCE
        except Exception as fallback_exc:
            print(f"Goldrank unavailable too: {fallback_exc}")
            previous_path=Path("ipo-feed.json")
            if not previous_path.exists():raise
            entries=[dict(item) for item in json.loads(previous_path.read_text(encoding="utf-8")).get("ipos",[])]
            source_used="preserved-existing-feed"
            print(f"Preserving {len(entries)} existing IPOs; attempting listing-date updates")
    # Preserve verified listing dates across scheduled calendar refreshes.
    old_path=Path("ipo-feed.json")
    if old_path.exists():
        previous=json.loads(old_path.read_text(encoding="utf-8"))
        known={normalized(x["name"]):x.get("listingDate") for x in previous.get("ipos",[]) if x.get("listingDate")}
        for item in entries:
            if normalized(item["name"]) in known:
                item["listingDate"]=known[normalized(item["name"])]
    try:
        finuts=finuts_dates(entries)
        for item in entries:
            date=finuts.get(normalized(item["name"]))
            if date:item["listingDate"]=date
        print(f"Finuts matched {len(finuts)} listing dates")
    except Exception as exc:
        print(f"Finuts unavailable: {exc}")
    # Prefer 38 listing dates, then check official KRX KIND.
    listing_sources_ok=0
    try:
        published=listings38()
        listing_sources_ok+=1
        for item in entries:
            date=published.get(normalized(item["name"]))
            if date:item["listingDate"]=date
        print(f"38 listing matches: {sum(normalized(x['name']) in published for x in entries)}")
    except Exception as exc:
        print(f"38 listings unavailable; retaining previous dates: {exc}")
    # Primary: official KRX KIND IPO company table. Only published listing dates are applied.
    try:
        official=kind_listing_dates()
        listing_sources_ok+=1
        for item in entries:
            key=re.sub(r"\s+","",item["name"])
            match=official.get(key)
            if match:
                item["listingDate"]=match
        print(f"KRX KIND matched {sum(bool(i.get('listingDate')) for i in entries)} IPO listing dates")
    except Exception as exc:
        print(f"KRX KIND unavailable; preserving existing dates: {exc}")
    # Secondary cross-check. Never infer a listing date from subscription or refund dates.
    try:
        confirmed=listing_dates()
        listing_sources_ok+=1
        for item in entries:
            match=confirmed.get(re.sub(r"\s+","",item["name"]))
            if match and not item.get("listingDate"):
                item["listingDate"]=match
        print("Secondary source cross-check completed")
    except Exception as exc:
        print(f"Secondary listing source unavailable: {exc}")
    if listing_sources_ok==0:
        raise RuntimeError("All listing-date sources failed; refusing to publish a misleading successful refresh")
    if len(entries)<5:
        raise RuntimeError(f"Unexpected source format: only {len(entries)} entries; preserving last good feed")
    Path("ipo-feed.json").write_text(json.dumps({"updatedAt":datetime.now(timezone.utc).isoformat(),"source":source_used,"ipos":entries},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Saved {len(entries)} IPOs")
if __name__=="__main__": main()
