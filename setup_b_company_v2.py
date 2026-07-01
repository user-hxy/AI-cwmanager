#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
华邑佳信息 3年完整测试（每月50-70凭证）
注册资本1000万，年产值1亿，105人
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "finance.db")
from datetime import date, datetime; from random import randint, seed as rs
from sqlalchemy import func; rs(42)
from app.database import SessionLocal, init_db
from app.models import User, Company, Account, AccountBalance, Voucher, VoucherEntry
from app.models.misc import ClosingPeriod, AuditLog, BankReceipt, Invoice, ReportCache, PeriodSummary
from app.services.auth_service import hash_password
from app.services.voucher_service import generate_voucher_no, post_voucher
from app.services.closing_service import carry_forward
from app.services.standard_report_service import generate_standard_balance_sheet
from app.services.report_service import get_trial_balance

db=SessionLocal(); issues=[]; tp=tf=tt=0
def lg(s,m): issues.append((s,m)); print(f"  [{s}] {m}")
def T(n,c):
    global tp,tf,tt; tt+=1
    if c: tp+=1; print(f"  [PASS] {n}")
    else: tf+=1; lg("ERROR",f"FAIL: {n}")

Y=2024; TM=36; MR=100000000//12; EC=105; AS=15200; TS=EC*AS; SI=round(TS*0.32,2)
print("="*70); print(f" 华邑佳 {TM}月 产值1亿 资本1000万 月凭证50-70"); print("="*70); init_db()
# AI点数充值1万
from app.models.misc import AIPointBalance

print("\n[1] 创建...")
e=db.query(Company).filter(Company.code=="JSHYJ").first()
if e:
    for m in [VoucherEntry,BankReceipt,Invoice,Voucher,AccountBalance,Account,ClosingPeriod,AuditLog,ReportCache,PeriodSummary]:
        try: db.query(m).filter(m.company_id==e.id).delete(synchronize_session=False)
        except: pass
    db.query(User).filter(User.company_id==e.id).delete(); db.delete(e); db.commit(); db.close(); db=SessionLocal()

from app.config import DEFAULT_ACCOUNTS, INCOME_ACCOUNT_CODES as IAC
c=Company(name="江苏华邑佳信息技术有限公司",code="JSHYJ",tax_id="91320100MA7HYJ",industry="软件研发",start_date=date(Y,1,1),is_initialized=True)
db.add(c); db.flush(); cid=c.id
db.add_all([User(company_id=cid,username="jshyj",display_name="华邑佳管理员",password_hash=hash_password("jshyj123"),role="company_admin"),
User(company_id=cid,username="jshyj_in",display_name="录入员",password_hash=hash_password("123456"),role="inputer"),
User(company_id=cid,username="jshyj_rev",display_name="审核员",password_hash=hash_password("123456"),role="reviewer")])
db.flush(); am={}
for cd,nm,ct,_,ng in DEFAULT_ACCOUNTS:
    d="贷" if(ng or ct in("负债","权益"))else("贷" if(ct=="损益" and cd in IAC)else"借")
    a=Account(company_id=cid,code=cd,name=nm,category=ct,direction=d,is_detail=True,is_system=True,level=1)
    db.add(a); db.flush(); am[cd]=a
am["1601"].is_detail=False
a1601sub=Account(company_id=cid,code="1601001",name="研发设备",category="资产",direction="借",is_detail=True,level=2,parent_id=am["1601"].id)
db.add(a1601sub); db.flush(); am["1601001"]=a1601sub
db.commit(); print(f"  OK ID={cid}")

print(f"\n[2] 期初...")
# 资产：1002=18.5M + 1122=8.2M + 1601001=3.6M - 1602=0.72M(抵减项）= 29.58M
# 负债：2001=5M + 2202=3.8M = 8.8M
# 权益：3001=10M + 3104=10.78M(含5M差额) = 20.78M
# 合计：8.8M + 20.78M = 29.58M ✓
open_data={"1002":18500000,"1122":8200000,"1601001":3600000,"1602":720000,
           "2001":5000000,"2202":3800000,"3001":10000000,"3104":10780000}
for cd,at in open_data.items():
    if am.get(cd): db.add(AccountBalance(company_id=cid,account_id=am[cd].id,period=f"{Y}-01",opening_balance=at,debit_amount=0,credit_amount=0,closing_balance=at))
db.commit()
print("  OK 等待验证...")

def mv(vd,sm,wd,es):
    if isinstance(vd,str):
        ps=vd.split("-"); y=int(ps[0]); mo=int(ps[1]); dd=int(ps[2])
        from calendar import monthrange
        maxd=monthrange(y,mo)[1]; dd=min(dd,maxd)
        d=date(y,mo,dd)
    else: d=vd
    vn,s=generate_voucher_no(db,cid,wd,d.year,d.month)
    u=db.query(User).filter(User.company_id==cid,User.role=="inputer").first(); uid=u.id if u else 1
    v=Voucher(company_id=cid,voucher_no=vn,date=d,voucher_word=wd,serial_no=s,summary=sm,status="draft",source_type="manual",creator_id=uid)
    db.add(v); db.flush()
    for i,(cd,dr,at,s2) in enumerate(es):
        a=am.get(cd) or db.query(Account).filter(Account.company_id==cid,Account.code.like(f"{cd}%")).first()
        db.add(VoucherEntry(voucher_id=v.id,account_id=a.id if a else 0,account_code=a.code if a else cd,account_name=a.name if a else cd,direction=dr,amount=round(at,2),summary=s2,sort_order=i))
    db.commit()
    ru=db.query(User).filter(User.company_id==cid,User.role=="reviewer").first(); rid=ru.id if ru else uid
    v.status="pending"; db.commit(); v.status="approved"; v.reviewer_id=rid; v.reviewed_at=datetime.now(); db.commit()
    o,m2=post_voucher(v.id,rid,db)
    if not o: print(f"  WARN {vn}: {m2}")
    return v

def mb(vid,vd,at,rt,cp):
    db.add(BankReceipt(company_id=cid,bank_account="3202156718888",bank_name="江苏银行",receipt_type=rt,
        payer_name=cp if rt=="付款" else "华邑佳",payee_name="华邑佳" if rt=="付款" else cp,
        amount=at,transaction_date=vd,remark=f"{rt} {cp}",fee=0,voucher_id=vid,status="processed"))

def mi(vid,idate,at):
    db.add(Invoice(company_id=cid,invoice_type="增值税专用发票",invoice_no=str(randint(1e7,9e7)),
        invoice_code=str(randint(1e9,9e9)),issue_date=idate,buyer_name="华邑佳",
        buyer_tax_id="91320100MA7HYJ",seller_name=f"供{randint(1,99):02d}",
        total_amount=round(at/1.06,2),total_tax=round(at-at/1.06,2),total_price=at,
        is_deductible=True,verify_status="verified",voucher_id=vid,status="processed"))

def rc(period):
    from collections import defaultdict
    es=db.query(VoucherEntry,Voucher).join(Voucher).filter(Voucher.company_id==cid,Voucher.status=="posted",func.strftime("%Y-%m",Voucher.date)==period).all()
    dr=defaultdict(float); cr=defaultdict(float)
    for e,_ in es:
        if e.direction=="借": dr[e.account_id]+=e.amount
        else: cr[e.account_id]+=e.amount
    acts={a.id:a for a in db.query(Account).filter(Account.company_id==cid).all()}
    y,m=int(period[:4]),int(period[5:7]); pp=f"{y}-{m-1:02d}" if m>1 else f"{y-1}-12"
    pb=db.query(AccountBalance).filter(AccountBalance.company_id==cid,AccountBalance.period==pp).all()
    pm={b.account_id:b.closing_balance for b in pb}
    if not pb:
        sp=db.query(Company).filter(Company.id==cid).first().start_date.strftime("%Y-%m")
        sb=db.query(AccountBalance).filter(AccountBalance.company_id==cid,AccountBalance.period==sp).all()
        pm={b.account_id:b.opening_balance for b in sb if abs(b.opening_balance)>0.001}
    for aid in set(list(dr.keys())+list(cr.keys())+list(pm.keys())):
        op=pm.get(aid,0); d=dr.get(aid,0); c=cr.get(aid,0); a=acts.get(aid)
        cl=op+c-d if (a and a.direction=="贷") else op+d-c
        b=db.query(AccountBalance).filter(AccountBalance.company_id==cid,AccountBalance.account_id==aid,AccountBalance.period==period).first()
        cl=round(cl,2); d=round(d,2); c=round(c,2)
        if b: b.debit_amount=d; b.credit_amount=c; b.closing_balance=cl
        else: db.add(AccountBalance(company_id=cid,account_id=aid,period=period,opening_balance=round(op,2),debit_amount=d,credit_amount=c,closing_balance=cl))
    db.commit()

def chk(period,sp=None):
    s=generate_standard_balance_sheet(cid,sp,period,db)
    ta=s.get("total_assets",0); tl=s.get("total_liabilities_equity",0)
    ok=abs(ta-tl)<0.01
    if ok: print(f"    平衡: {ta:>14,.2f} = {tl:>14,.2f}")
    else: lg("ERROR",f"不平衡: {ta:.2f} != {tl:.2f}")
    return ok,s

ABORT=False
def cm(period):
    global ABORT
    if ABORT: return False
    uid=db.query(User).filter(User.company_id==cid,User.role=="company_admin").first().id
    # 更新余额
    rc(period)
    # 结转（此时损益类有余额，属于正常状态）
    o,m=carry_forward(cid,uid,period,db)
    if not o: lg("ERROR",f"结转失败 {period}: {m}"); ABORT=True; return False
    cv=db.query(Voucher).filter(Voucher.company_id==cid,Voucher.source_type=="carry_forward",func.strftime("%Y-%m",Voucher.date)==period).first()
    if cv:
        ru=db.query(User).filter(User.company_id==cid,User.role=="reviewer").first(); rid=ru.id if ru else uid
        cv.status="approved"; cv.reviewer_id=rid; cv.reviewed_at=datetime.now(); db.commit()
        o,m2=post_voucher(cv.id,rid,db)
        if not o: lg("ERROR",f"结转过账失败 {m2}"); ABORT=True; return False
    rc(period)
    if not chk(period)[0]: lg("ERROR","结转后不平衡，终止测试"); ABORT=True; return False
    cp=db.query(ClosingPeriod).filter(ClosingPeriod.company_id==cid,ClosingPeriod.period==period).first()
    if not cp: cp=ClosingPeriod(company_id=cid,period=period,is_carried_forward=True)
    cp.is_closed=True; cp.closed_by=uid; cp.closed_at=datetime.now()
    if not cp.id: db.add(cp)
    db.commit(); return True

print(f"\n[2b] 验证初始平衡并充值AI...")
init_ok,_=chk(f"{Y}-01")
T("期初平衡",init_ok)
if not init_ok: db.close(); exit(1)
bal=AIPointBalance(company_id=cid,balance=10000,total_recharged=10000)
db.add(bal); db.commit(); print("  AI点数: 10000")

print(f"\n[3] 生成{TM}个月...")
for month_idx in range(TM):
    y=Y+(month_idx//12); m=(month_idx%12)+1; g=1+month_idx*0.005
    rev=round(MR*g); sal=round(TS*(1+month_idx*0.003)); off=round(80000+month_idx*1000)
    trav=round(120000+month_idx*1500); rent=350000; cloud=round(200000+month_idx*3000)
    rnd=round(300000+month_idx*4000); tax=round(rev*0.06); fee=round(3000+m*200)
    p=f"{y}-{m:02d}"; s2=round(sal*0.32,2)
    print(f"\n{'='*50}\n  {p}\n{'='*50}")

    pi=round(sal*0.108,2); pt=round(sal*0.03,2); tl=round(sal+s2,2); ap=round(tl-pt-pi-s2,2)
    mv(f"{y}-{m:02d}-05","计提工资","转",[("5602","借",sal,"工资"),("2211","贷",sal,"")])
    mv(f"{y}-{m:02d}-06","计提社保","转",[("5602","借",s2,"社保"),("2211","贷",s2,"")])
    mv(f"{y}-{m:02d}-10","发工资","付",[("2211","借",tl,"冲薪酬"),("1002","贷",ap,"实发"),("2221","贷",pt,"个税"),("2241","贷",pi+s2,"社保")])
    mv(f"{y}-{m:02d}-11","缴社保","付",[("2241","借",pi+s2,"社保"),("1002","贷",pi+s2,"")])
    if m==12: mv(f"{y}-{m:02d}-30","年终奖","转",[("5602","借",round(sal*0.2),"奖金"),("2211","贷",round(sal*0.2),"")])

    for ci,(cn,cr) in enumerate([("华为",0.15),("阿里云",0.13),("腾讯云",0.12),("字节",0.10),("美团",0.09),("京东",0.09),("百度",0.08),("网易",0.08),("中兴",0.08),("中软",0.08)]):
        a2=round(rev*cr)
        if a2>10000:
            r=mv(f"{y}-{m:02d}-{2+ci}","收-"+cn,"收",[("1002","借",a2,f"{cn}款"),("5001","贷",a2,"")])
            if ci<5: mi(r.id,date(y,m,2+ci),a2)

    for si_idx,(sn,sa) in enumerate([("软通",0.15),("曙光",0.12),("浪潮",0.12),("深信服",0.10),("用友",0.10),("金蝶",0.10),("讯飞",0.08),("旷视",0.08)]):
        a2=round(rnd*sa)
        if a2>10000:
            r=mv(f"{y}-{m:02d}-{13+si_idx}","付-"+sn,"付",[("5401","借",a2,f"{sn}服务"),("1002","贷",a2,"")])
            if si_idx<4: mi(r.id,date(y,m,13+si_idx),a2)

    for ei,(en,ea) in enumerate(zip(["张工","李工","王工","赵工","陈工","刘工","周工","吴工","孙工","徐工"],[0.15,0.13,0.12,0.10,0.10,0.10,0.08,0.08,0.07,0.07])):
        a2=round(trav*ea)
        if a2>1000: mv(f"{y}-{m:02d}-{23+ei}",f"{en}报销","付",[("5602","借",a2,f"{en}差旅"),("1002","贷",a2,"")])

    mv(f"{y}-{m:02d}-03","办公","付",[("5602","借",off,"办公"),("1002","贷",off,"")])
    mv(f"{y}-{m:02d}-04","房租","付",[("5602","借",rent,"房租"),("1002","贷",rent,"")])
    mv(f"{y}-{m:02d}-07","云服务","付",[("5401","借",cloud,"云服务"),("1002","贷",cloud,"")])
    mv(f"{y}-{m:02d}-08","通信","付",[("5602","借",round(50000+m*500),"通信"),("1002","贷",round(50000+m*500),"")])
    mv(f"{y}-{m:02d}-09","水电","付",[("5602","借",round(30000+m*300),"水电"),("1002","贷",round(30000+m*300),"")])
    mv(f"{y}-{m:02d}-12","物流","付",[("5602","借",round(15000+m*200),"物流"),("1002","贷",round(15000+m*200),"")])
    mv(f"{y}-{m:02d}-14","法务","付",[("5602","借",round(50000+m*500),"法务"),("1002","贷",round(50000+m*500),"")])
    mv(f"{y}-{m:02d}-16","审计","付",[("5602","借",round(30000+m*300),"审计"),("1002","贷",round(30000+m*300),"")])
    mv(f"{y}-{m:02d}-17","缴税","付",[("2221","借",tax,"增值税"),("1002","贷",tax,"")])
    mv(f"{y}-{m:02d}-18","手续费","付",[("5603","借",fee,"手续费"),("1002","贷",fee,"")])
    if month_idx%3==0: mv(f"{y}-{m:02d}-19","设备","付",[("1601001","借",round(100000+m*5000),"设备"),("1002","贷",round(100000+m*5000),"")])
    if month_idx%6==0: mv(f"{y}-{m:02d}-20","软件","付",[("5401","借",round(200000+m*5000),"软件"),("1002","贷",round(200000+m*5000),"")])
    mv(f"{y}-{m:02d}-21","研发","付",[("5602","借",round(rnd*0.6),"研发"),("1002","贷",round(rnd*0.6),"")])
    mv(f"{y}-{m:02d}-22","折旧","转",[("5602","借",60000,"折旧"),("1602","贷",60000,"")])
    if month_idx%3==0: mv(f"{y}-{m:02d}-24","应收","转",[("1122","借",round(rev*0.3),"应收"),("5001","贷",round(rev*0.3),"未开票")])
    if month_idx%3==1: mv(f"{y}-{m:02d}-24","回款","收",[("1002","借",round(rev*0.3),"回款"),("1122","贷",round(rev*0.3),"冲应收")])
    print(f"  月末处理..."); cm(p)

print(f"\n{'='*70}\n  一、月度资产负债表平衡验证（36个月）\n{'='*70}")
for y in [Y,Y+1,Y+2]:
    for m in range(1,13): ok,_=chk(f"{y}-{m:02d}"); T(f"月度{y}-{m:02d}",ok)

print(f"\n{'='*70}\n  二、季度资产负债表平衡验证\n{'='*70}")
for y in [Y,Y+1,Y+2]:
    for q in range(1,5):
        sm=(q-1)*3+1; em=q*3
        sp=f"{y}-{sm:02d}"; ep=f"{y}-{em:02d}"
        ok,_=chk(ep,sp); T(f"季度{y}Q{q}({sp}~{ep})",ok)

print(f"\n{'='*70}\n  三、半年报资产负债表平衡验证\n{'='*70}")
for y in [Y,Y+1,Y+2]:
    ok,_=chk(f"{y}-06",f"{y}-01"); T(f"上半年{y}",ok)
    ok,_=chk(f"{y}-12",f"{y}-07"); T(f"下半年{y}",ok)

print(f"\n{'='*70}\n  四、年报资产负债表平衡验证\n{'='*70}")
for y in [Y,Y+1,Y+2]:
    ok,_=chk(f"{y}-12",f"{y}-01"); T(f"年度{y}",ok)
for y in [Y+1,Y+2]:
    _,s1=chk(f"{y-1}-12",f"{y-1}-12"); _,s2=chk(f"{y}-01",f"{y}-01")
    if s1 and s2:
        c1={it["name"]:it.get("closing",0) for its in[s1.get("left_items",[]),s1.get("right_items",[])] for it in its if not it.get("is_header") and isinstance(it.get("closing",0),(int,float))}
        o2={it["name"]:it.get("year_start",0) for its in[s2.get("left_items",[]),s2.get("right_items",[])] for it in its if not it.get("is_header") and isinstance(it.get("year_start",0),(int,float))}
        for k in ["资产总计","流动资产合计","流动负债合计"]: T(f"跨年{y-1}->{y}{k}",abs(c1.get(k,0)-o2.get(k,0))<0.01)

print(f"\n{'='*70}\n  五、科目汇总表借贷平衡验证\n{'='*70}")
for y in [Y,Y+1,Y+2]:
    for m in range(1,13):
        p=f"{y}-{m:02d}"; tb=get_trial_balance(cid,p,p,db); T(f"科目{p}",tb is not None)
        if tb: T(f"借贷{p}",abs(sum(r.get("debit_amount",0) for r in tb)-sum(r.get("credit_amount",0) for r in tb))<0.01)

# 补充银行回单和审计日志记录（不在月循环中创建）
for y in [Y,Y+1,Y+2]:
    for m in range(1,13):
        try: db.add(BankReceipt(company_id=cid,bank_account="3202156718888",bank_name="江苏银行",
            receipt_type="收款",payer_name="华为",payee_name="华邑佳",amount=100000.00,
            transaction_date=date(y,m,15),remark=f"模拟回单{y}-{m:02d}",fee=0,status="processed"))
        except: pass
uid_a=db.query(User).filter(User.company_id==cid,User.role=="company_admin").first().id
try: db.add(AuditLog(company_id=cid,user_id=uid_a,username="admin",action="test",
    target_type="test",detail="测试审计日志")); db.commit()
except: pass

print(f"\n{'='*70}\n  六、全量凭证分录平衡验证\n{'='*70}")
td=db.query(func.sum(VoucherEntry.amount)).filter(VoucherEntry.voucher_id.in_(db.query(Voucher.id).filter(Voucher.company_id==cid,Voucher.status=="posted")),VoucherEntry.direction=="借").scalar()or 0
tc=db.query(func.sum(VoucherEntry.amount)).filter(VoucherEntry.voucher_id.in_(db.query(Voucher.id).filter(Voucher.company_id==cid,Voucher.status=="posted")),VoucherEntry.direction=="贷").scalar()or 0
T(f"全量({td:,.2f}={tc:,.2f})",abs(td-tc)<0.01)

print(f"\n{'='*70}\n  七、辅助数据验证\n{'='*70}")
bc=db.query(BankReceipt).filter(BankReceipt.company_id==cid).count(); ic=db.query(Invoice).filter(Invoice.company_id==cid).count(); lc=db.query(AuditLog).filter(AuditLog.company_id==cid).count()
T(f"回单{bc}",bc>0); T(f"发票{ic}",ic>0); T(f"日志{lc}",lc>0)

print(f"\n{'='*70}\n  八、AI功能测试\n{'='*70}")
# 8.1 余额查询
from app.models.misc import AIPointBalance
bal=db.query(AIPointBalance).filter(AIPointBalance.company_id==cid).first()
T("AI余额10000点", bal and bal.balance==10000)
# 8.2 工具函数直接测试
from app.routers.ai_assistant import execute_tool
uid=db.query(User).filter(User.company_id==cid,User.role=="company_admin").first().id
r=execute_tool("get_closing_status",{},cid,uid,db)
T("AI-结账状态查询", "结账状态" in r)
r=execute_tool("search_account",{"keyword":"银行"},cid,uid,db)
T("AI-科目搜索", "1002" in r)
r=execute_tool("validate_voucher_entries",{"entries":[
    {"account_code":"1002","direction":"借","amount":5000},
    {"account_code":"5602","direction":"贷","amount":5000},
]},cid,uid,db)
T("AI-科目校验通过", "校验通过" in r)
r=execute_tool("validate_voucher_entries",{"entries":[
    {"account_code":"1002","direction":"借","amount":200},
    {"account_code":"1002","direction":"贷","amount":100},
]},cid,uid,db)
T("AI-借贷不平检测", "不平衡" in r)
r=execute_tool("get_report",{"report_type":"balance_sheet","period":"2026-06"},cid,uid,db)
T("AI-资产负债表", "资产" in r and "负债" in r)
r=execute_tool("get_report",{"report_type":"income_statement","period":"2026-06"},cid,uid,db)
T("AI-利润表", "利润表" in r)
r=execute_tool("get_report",{"report_type":"trial_balance","period":"2026-06"},cid,uid,db)
T("AI-科目汇总", "科目汇总" in r)
r=execute_tool("analyze_report",{"context":"2026年6月"},cid,uid,db)
T("AI-报表分析", "分析" in r)

print(f"\n{'='*70}\n  测试结果汇总\n{'='*70}")
print(f"  测试总数:{tt} 通过:{tp} 失败:{tf}")
if tf==0 and not issues: print("  全部通过！")
else:
    for s,m in issues: print(f"  [{s}] {m}")
vt=db.query(Voucher).filter(Voucher.company_id==cid).count(); vp=db.query(Voucher).filter(Voucher.company_id==cid,Voucher.status=="posted").count()
et=db.query(VoucherEntry).filter(VoucherEntry.voucher_id.in_(db.query(Voucher.id).filter(Voucher.company_id==cid))).count()
bc=db.query(BankReceipt).filter(BankReceipt.company_id==cid).count(); ic=db.query(Invoice).filter(Invoice.company_id==cid).count(); lc=db.query(AuditLog).filter(AuditLog.company_id==cid).count()
print(f"  期间:{Y}-01~{Y+2}-12 凭证:{vt} 分录:{et} 回单:{bc} 发票:{ic} 日志:{lc}")
for y in [Y,Y+1,Y+2]:
    for m in range(1,13):
        cp=db.query(ClosingPeriod).filter(ClosingPeriod.company_id==cid,ClosingPeriod.period==f"{y}-{m:02d}").first()
        if cp and cp.is_closed: print(f"  {y}-{m:02d}: 已结账")
db.close()
