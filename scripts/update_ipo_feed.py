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
FINUTS_CALENDAR_API = "https://www.finuts.co.kr/html/task/ipo/ipoCalendarListQuery.php"

def finuts_calendar():
    """Use the live JSON endpoint called by Finuts' own calendar.
    S is subscription, K is an explicitly published listing event.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from urllib.parse import urlencode
    now = datetime.now(timezone.utc).date()
    base_month = now.year * 12 + now.month - 1

    def get_month(offset):
        month_number = base_month + offset
        month = f"{month_number // 12:04d}.{month_number % 12 + 1:02d}"
        qs = urlencode({
            "calendarDate": month,
            "checkedValue[]": ["K"],
        }, doseq=True)
        request = urllib.request.Request(
            FINUTS_CALENDAR_API + "?" + qs,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; IPOCalendarSync/1.0)",
                "Referer": FINUTS_SOURCE,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*",
            },
        )
        with urllib.request.urlopen(request, timeout=18) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = payload.get("data") if isinstance(payload, dict) else None
        if rows is None:
            return month, []
        if not isinstance(rows, list):
            raise RuntimeError(f"Finuts unexpected calendar data for {month}")
        return month, rows

    rows = []
    successful_months = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(get_month, offset) for offset in range(-4, 5)]
        for future in as_completed(futures):
            try:
                month, data = future.result()
                successful_months.append(month)
                rows.extend(data)
            except Exception as exc:
                print(f"Finuts calendar request failed: {exc}")

    if not successful_months or not rows:
        raise RuntimeError("Finuts calendar API did not return any events")

    subscriptions = {}
    listings = {}
    listing_conflicts = set()
    earliest = (now - timedelta(days=100)).isoformat()
    latest = (now + timedelta(days=150)).isoformat()

    for event in rows:
        if not isinstance(event, dict):
            continue
        category = str(event.get("SE_CD") or "")
        if category not in ("IPO", "SPAC"):
            continue
        name = str(event.get("ENT_NM") or "").strip()
        key = normalized(name)
        if not key:
            continue
        event_type = str(event.get("SCHDL_SE_CD") or "")
        if event_type == "K":
            date = str(event.get("IPO_DATE") or "").strip()
            try:
                datetime.fromisoformat(date)
            except ValueError:
                continue
            if key in listings and listings[key] != date:
                listing_conflicts.add(key)
            else:
                listings[key] = date
        elif event_type == "S":
            start = str(event.get("BGNG_YMD") or "").strip()
            end = str(event.get("END_YMD") or "").strip()
            try:
                datetime.fromisoformat(start)
                datetime.fromisoformat(end)
            except ValueError:
                continue
            if end < earliest or start > latest or end < start:
                continue
            item = {
                "name": name,
                "subscriptionStart": start,
                "subscriptionEnd": end,
                "brokers": str(event.get("INDCT_JUGANSA_NM") or ""),
                "type": "스팩" if category == "SPAC" else "일반공모주",
            }
            existing = subscriptions.get(key)
            if not existing or end > existing["subscriptionEnd"]:
                subscriptions[key] = item

    for key in listing_conflicts:
        listings.pop(key, None)
    if listing_conflicts:
        print(f"Finuts conflicting listing dates skipped for {len(listing_conflicts)} IPOs")
    print(f"Finuts API: {len(successful_months)} months, {len(subscriptions)} subscription records, {len(listings)} confirmed listing dates")
    if not subscriptions and not listings:
        raise RuntimeError("Finuts returned events but no usable subscription or listing dates")
    return list(subscriptions.values()), listings


def main():
    old_path = Path("ipo-feed.json")
    previous = json.loads(old_path.read_text(encoding="utf-8")) if old_path.exists() else {}
    old_entries = previous.get("ipos", [])
    today = datetime.now(timezone.utc).date()

    entries = []
    finuts_listings = {}
    finuts_ok = False
    source_used = FINUTS_SOURCE
    try:
        entries, finuts_listings = finuts_calendar()
        finuts_ok = True
    except Exception as exc:
        print(f"Finuts calendar unavailable: {exc}")

    try:
        goldrank = goldrank_feed()
        if not finuts_ok:
            entries = goldrank
            source_used = SOURCE
        else:
            known = {normalized(item["name"]) for item in entries}
            added = 0
            for item in goldrank:
                key = normalized(item["name"])
                if key not in known:
                    entries.append(item)
                    known.add(key)
                    added += 1
            print(f"Goldrank supplemental subscription records: {added}")
    except Exception as exc:
        print(f"Goldrank calendar unavailable: {exc}")

    # Preserve recently passed IPOs for late entries, and never discard a
    # previously verified listing date just because one source is temporarily empty.
    known = {normalized(item["name"]) for item in entries}
    for item in old_entries:
        key = normalized(item["name"])
        if key in known:
            continue
        end = item.get("subscriptionEnd", "")
        try:
            keep = datetime.fromisoformat(end).date() >= today - timedelta(days=21)
        except (ValueError, TypeError):
            keep = False
        if keep:
            entries.append(dict(item))
            known.add(key)

    old_dates = {
        normalized(item["name"]): item.get("listingDate")
        for item in old_entries if item.get("listingDate")
    }
    matches = 0
    for item in entries:
        key = normalized(item["name"])
        published_date = finuts_listings.get(key)
        if published_date:
            item["listingDate"] = published_date
            matches += 1
        elif old_dates.get(key):
            item["listingDate"] = old_dates[key]

    if len(entries) < 5:
        raise RuntimeError(f"Only {len(entries)} IPO entries available; refusing to replace the last feed")
    if not finuts_ok and not entries:
        raise RuntimeError("No live IPO calendar source available")

    entries.sort(key=lambda x: (x.get("subscriptionEnd", ""), x.get("name", "")))
    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": source_used,
        "listingSource": FINUTS_SOURCE if finuts_ok else "previously-verified-only",
        "listingMatches": matches,
        "ipos": entries,
    }
    old_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(entries)} IPOs; {matches} listing dates matched from Finuts; {sum(bool(x.get('listingDate')) for x in entries)} total dated IPOs")

if __name__ == "__main__":
    main()
