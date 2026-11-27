#!/usr/bin/env python3
"""
My Training — automatski testovi (end-to-end, u pravom pregledaču).

Svaki test otvara index.html u čistom pregledaču (prazan localStorage), pravi
sintetičke podatke i provjerava ponašanje aplikacije. Lični podaci se ne koriste.

Pokretanje:
    pip install playwright && python -m playwright install chromium
    python tests/run_tests.py            # svi testovi
    python tests/run_tests.py backup     # samo testovi čije ime sadrži "backup"

Opciono: CHROME_PATH=/putanja/do/chrome za sistemski Chrome umjesto Playwright Chromium-a.
         BROWSER=webkit za WebKit (isti engine kao Safari na iPhone-u; python -m playwright install webkit).
"""
import asyncio, datetime, functools, http.server, json, os, pathlib, subprocess, sys, tempfile, threading, traceback
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = (ROOT / "index.html").as_uri()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="mytraining-tests-"))
# Last version before the 2026-11-27 rework (Iteracija 7.13) — used for the upgrade test.
OLD_VERSION_COMMIT = "3548f85e5cbe0900fdb9e2c16df960a22343d66d"

def serve_repo():
    """Serves the repository over http://127.0.0.1 (service worker and offline mode need http)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/index.html"

# Shared fixture: two programs (Upper/Lower and a Full body program that repeats one workout).
SETUP = """()=>{closeDlg();delete S.noviKorisnik;delete S.bezCiklusa;S.ime='Test Korisnik';S.vokativ='Test';
 const n=x=>S.vezbe.find(v=>v.naziv===x).id;
 S.treningBiblioteka=[
  {id:'u',naziv:'Upper A',tip:'Upper',stavke:[{id:'a',vezbaId:n('Machine Chest Press'),b:3,pon:'8–10',odmor:'2 min'},{id:'b',vezbaId:n('Lat Pulldown — Wide Grip'),b:3,pon:'10–12',odmor:'2 min'}]},
  {id:'l',naziv:'Lower A',tip:'Lower',stavke:[{id:'d',vezbaId:n('Hack Squat'),b:4,pon:'8',odmor:'3 min'},{id:'e',vezbaId:n('Seated Leg Curl'),b:3,pon:'10',odmor:'90 s'}]},
  {id:'f',naziv:'Full B',tip:'Full body',stavke:[{id:'g',vezbaId:n('Leg Press'),b:3,pon:'10'},{id:'h',vezbaId:n('Seated Cable Row'),b:3,pon:'10'}]}];
 S.programBiblioteka=[{id:'p1',naziv:'UL',treningIds:['u','l']},{id:'p2',naziv:'FB',treningIds:['f','f']}];save()}"""

TESTS = []
def test(fn):
    TESTS.append(fn); return fn

class Ctx:
    def __init__(self, page, errors): self.pg, self.errors = page, errors
    async def ev(self, js, arg=None):
        return await (self.pg.evaluate(js, arg) if arg is not None else self.pg.evaluate(js))
    async def wait(self, ms=150): await self.pg.wait_for_timeout(ms)
    async def setup(self): await self.ev(SETUP)
    async def go(self, tab, ctx="{}"): await self.ev(f"go('{tab}',{ctx})"); await self.wait()
    async def new_cycle(self, program_id):
        await self.go("vise"); await self.pg.click("#cNovi"); await self.wait()
        await self.pg.select_option("#mProgram", program_id); await self.pg.click("#mSave"); await self.wait(200)
    async def start_workout(self, label_prefix=None):
        await self.go("danas")
        if label_prefix:
            val = await self.ev(f"[...document.querySelectorAll('#dSab option')].find(o=>o.textContent.startsWith({json.dumps(label_prefix)})).value")
            await self.pg.select_option("#dSab", val)
        await self.pg.click("#dStart"); await self.wait()
    async def set_row(self, i, j, kg, reps, confirm=True):
        await self.pg.fill(f'input[data-f="{i}:{j}:kg"]', str(kg))
        await self.pg.fill(f'input[data-f="{i}:{j}:pon"]', str(reps))
        if confirm: await self.pg.click(f'[data-ok="{i}:{j}"]'); await self.wait(80)
    async def finish(self):
        await self.pg.click("#hbFinish"); await self.wait(300)
    async def close(self): await self.ev("closeDlg()")

def check(cond, msg):
    if not cond: raise AssertionError(msg)

# ---------------------------------------------------------------- tests

@test
async def new_user_starts_empty(t: Ctx):
    s = json.loads(await t.ev("JSON.stringify({ime:S.ime,logs:S.dnevnik.length,lib:(S.treningBiblioteka||[]).length,prog:(S.programBiblioteka||[]).length,cyc:S.mezociklusi.length,vezbe:S.vezbe.length,welcome:document.getElementById('dlg').open,bez:!!S.bezCiklusa})"))
    check(s["ime"] == "" and s["logs"] == 0 and s["lib"] == 0 and s["prog"] == 0 and s["cyc"] == 0, f"nova instalacija nije prazna: {s}")
    check(s["vezbe"] > 100, "nema biblioteke vježbi")
    check(s["welcome"] and s["bez"], "nema dobrodošlice ili rada bez ciklusa za novog korisnika")
    await t.pg.fill("#wIme", "Ana"); await t.pg.click("#wOk"); await t.wait()
    check(await t.pg.inner_text("#ttl") == "Ana", "naslov nije ime korisnika")
    msgs = await t.ev("S.vokativ='';[...Array(20)].map((_,i)=>workoutMessage([120,100,90,75,55,30][i%6]))")
    check(not any("Ivan" in m or "prešao" in m or "Razbio" in m for m in msgs), f"lične ili rodne poruke: {msgs}")

@test
async def existing_data_keeps_name(t: Ctx):
    await t.ev("""()=>{const d=JSON.parse(localStorage.getItem(KEY));delete d.ime;delete d.vokativ;delete d.noviKorisnik;d.dnevnik.push({id:'x',datum:'2026-09-01',vezbaId:d.vezbe[0].id,serije:1,pon:5,kg:10});localStorage.setItem(KEY,JSON.stringify(d))}""")
    await t.pg.reload(); await t.wait(500)
    check(await t.pg.inner_text("#ttl") == "Ivan Lero", "postojeći podaci su izgubili ime")
    check(not await t.ev("!!document.getElementById('wIme')"), "dobrodošlica se prikazala postojećem korisniku")

@test
async def set_confirmation_and_finish(t: Ctx):
    await t.setup(); await t.new_cycle("p1"); await t.start_workout("Upper A")
    await t.set_row(0, 0, 50, 10)
    await t.set_row(0, 1, 50, 11, confirm=False)
    check(await t.ev("doneCount(sesija.stavke[0])") == 1, "upis ponavljanja bez ✓ ne smije označiti set")
    await t.pg.click('[data-ok="0:1"]'); await t.wait(80)
    check(await t.ev("doneCount(sesija.stavke[0])") == 2, "✓ nije potvrdio set")
    await t.pg.click('[data-ok="0:1"]'); await t.wait(80)
    u = json.loads(await t.ev("JSON.stringify(sesija.stavke[0].unosi[1])"))
    check(u["pon"] == "11" and u["done"] is False, f"poništavanje ✓ je obrisalo podatke: {u}")
    # empty reps + ✓ = suggestion (bottom of range)
    await t.pg.click('[data-ok="1:0"]'); await t.wait(80)
    check(await t.ev("sesija.stavke[1].unosi[0].pon") == "10", "✓ na praznom setu nije upisao predlog")
    prompts = []
    t.pg.remove_listener("dialog", t._dlg)
    async def on_dialog(d): prompts.append(d.message); await d.accept()
    t.pg.on("dialog", lambda d: asyncio.ensure_future(on_dialog(d)))
    await t.finish()
    check(any("nije potvrđeno" in p for p in prompts), "nema upozorenja za nepotvrđene setove")
    check(await t.ev("S.dnevnik.length") == 3, "pogrešan broj upisanih setova")

@test
async def reduce_plan_removes_unconfirmed(t: Ctx):
    await t.setup(); await t.new_cycle("p1"); await t.start_workout("Upper A")
    for j in range(3): await t.set_row(0, j, 40, 9, confirm=False)
    await t.pg.click('[data-menu="0"]'); await t.wait(); await t.pg.click('[data-m="minus"]'); await t.wait()
    r = await t.ev("sesija.stavke[0].plan+'/'+sesija.stavke[0].unosi.length")
    check(r == "2/2", f"smanjenje plana nije uklonilo popunjen nepotvrđen set: {r}")
    check(await t.ev("document.querySelectorAll('[data-del]').length") == 0, "dugme za brisanje seta ne treba da postoji")

@test
async def myo_rep_counts_as_two(t: Ctx):
    await t.setup(); await t.new_cycle("p1"); await t.start_workout("Upper A")
    await t.pg.click('[data-tip="0:0"]'); await t.wait(80)
    await t.pg.fill('input[data-f="0:0:mini"]', "4+4+3"); await t.set_row(0, 0, 50, 12)
    check(await t.ev("doneCount(sesija.stavke[0])") == 2, "myo set se ne broji kao 2")
    await t.finish(); await t.close()
    l = json.loads(await t.ev("JSON.stringify(S.dnevnik.slice(-1)[0])"))
    check(l["serije"] == 2 and l["tip"] == "myo" and l["mini"] == "4+4+3", f"myo zapis neispravan: {l}")
    check(await t.ev(f"bestLogged('{l['vezbaId']}')") is None, "myo set ne smije ulaziti u rekorde")

@test
async def best_result_and_pr(t: Ctx):
    await t.setup()
    await t.ev("""()=>{const v=S.vezbe.find(x=>x.naziv==='Machine Chest Press').id;[['2026-10-01',42.5,5],['2026-10-03',40,12]].forEach(([d,kg,p])=>S.dnevnik.push({id:uid(),datum:d,vezbaId:v,serije:1,pon:p,kg}));save()}""")
    b = json.loads(await t.ev("JSON.stringify(bestLogged(S.vezbe.find(x=>x.naziv==='Machine Chest Press').id))"))
    check(b["kg"] == 40 and b["pon"] == 12, f"najbolji rezultat nije po e1RM: {b}")
    pr = await t.ev("isNewPR(S.vezbe.find(x=>x.naziv==='Machine Chest Press').id,'2026-10-10',[{kg:'40',pon:'13'}])")
    check("najbolji" in pr, f"novi rekord nije prepoznat: {pr}")

@test
async def progress_chart_metrics(t: Ctx):
    await t.setup()
    await t.ev("""()=>{const v=S.vezbe.find(x=>x.naziv==='Leg Press').id;[['2026-11-02',80,10],['2026-11-05',85,8],['2026-11-09',90,7]].forEach(([d,kg,r])=>S.dnevnik.push({id:uid(),datum:d,vezbaId:v,serije:1,pon:r,kg}));save();pregledMode='vezba';CTX.progressVid=v;go('pregled',{progressVid:v})}""")
    await t.wait()
    for m in ["e1", "kg", "pon"]:
        await t.pg.click(f'[data-pmetric="{m}"]'); await t.wait()
    txt = await t.pg.inner_text("#view")
    check("Najviše ponavljanja" in txt and "+0" not in txt.split("PROGRESIJA")[0], "grafik ne mijenja metriku")

@test
async def pdf_export_is_valid(t: Ctx):
    await t.setup()
    await t.ev("""()=>{const v=S.vezbe.find(x=>x.naziv==='Leg Press').id;S.dnevnik.push({id:uid(),datum:'2026-11-02',vezbaId:v,serije:1,pon:10,kg:80,napomena:'test'});save()}""")
    data = await t.ev("""(async()=>{const blob=pdfFromPages(pdfRenderPages(completedWorkoutBlocks(S.dnevnik,null)));const b=new Uint8Array(await blob.arrayBuffer());return [String.fromCharCode(...b.slice(0,8)),String.fromCharCode(...b.slice(-6)),b.length]})()""")
    check(data[0].startswith("%PDF-1.4") and "%%EOF" in data[1] and data[2] > 5000, f"PDF nije ispravan: {data}")

@test
async def free_workout_weekly_volume_and_template(t: Ctx):
    await t.setup(); await t.new_cycle("p1"); await t.go("danas")
    await t.pg.click("#dCustom"); await t.wait(); await t.pg.click("#fsGo"); await t.wait()
    await t.ev("const v=S.vezbe.find(x=>x.naziv==='Hack Squat').id;sesija.stavke.push({vezbaId:v,plan:3,pon:'',odmor:'',unosi:makeSetRows(v,3,sesija.datum)});render()")
    await t.set_row(0, 0, 100, 8); await t.set_row(0, 1, 100, 10)
    vol = await t.pg.inner_text("#view")
    check("Sedmični volumen" in vol.upper().title() or "SEDMIČNI VOLUMEN" in vol, "nema kartice sedmičnog volumena")
    t.pg.remove_listener("dialog", t._dlg)
    t.pg.on("dialog", lambda d: asyncio.ensure_future(d.accept("Slobodni test") if d.type == "prompt" else d.accept()))
    await t.finish()
    check(await t.ev("Object.values(S.sedmicniStatus).every(w=>!Object.keys(w).length)"), "dodatni slobodni trening ne smije označiti planirani")
    await t.pg.click("#sumTpl"); await t.wait()
    tpl = json.loads(await t.ev("JSON.stringify(LIB().slice(-1)[0])"))
    check(tpl["naziv"] == "Slobodni test" and tpl["stavke"][0]["b"] == 2 and tpl["stavke"][0]["pon"] == "8–10", f"šablon neispravan: {tpl}")

@test
async def same_workout_twice_in_program(t: Ctx):
    await t.setup()
    await t.ev("newProgramDialog()"); await t.wait()
    await t.pg.click('[data-pfreq="3"]'); await t.pg.fill("#pName", "FB 3x")
    for i in range(3):
        await t.pg.click(f'[data-pe="{i}"]'); await t.wait(80); await t.pg.click('#dlg2Body [data-pid="f"]'); await t.wait(80)
    t.pg.remove_listener("dialog", t._dlg); t.pg.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
    await t.pg.click("#pSave"); await t.wait()
    p = json.loads(await t.ev("JSON.stringify(PROG().slice(-1)[0])"))
    check(p["treningIds"] == ["f", "f", "f"], f"forma ne dozvoljava isti trening više puta: {p}")
    await t.ev("startOpenPeriod(PROG().slice(-1)[0]);render()")
    check(await t.ev("weeklyPlanIds().length") == 3, "sedmični plan ne broji ponavljanja istog treninga")
    await t.start_workout("Full B (1)"); await t.set_row(0, 0, 80, 10); await t.finish(); await t.close()
    st = await t.ev("weeklyPlanIds().map(id=>plannedWorkoutStatus(id)).join(',')")
    check(st == "done,pending,pending", f"statusi ponavljanja nisu zasebni: {st}")

@test
async def open_period_and_cycle_end_prompt(t: Ctx):
    await t.setup()
    await t.ev("""()=>{const c={id:'m1',naziv:'M1',pocetak:'2026-01-05',trajanje:6,nedelje:weekPreset(6),deloadPct:60,status:'aktivan',sourceProgramId:'p1',programNaziv:'UL',progresija:{midAdd:1,peakAdd:2},sabloni:librarySnapshot(['u','l'],{midAdd:1,peakAdd:2})};S.mezociklusi=[c];S.aktivniMezociklusId='m1';save();location.reload()}""")
    await t.wait(700)
    check("je završen" in (await t.ev("document.getElementById('dlg').open?document.querySelector('#dlgBody h2').textContent:''")), "nema pitanja po završetku ciklusa")
    check(await t.ev("planSerija({b:3,prog:true},faza(cikNedelja(),activeCycle()))") == 3, "posle ciklusa plan nije osnovni")
    await t.pg.click("#ceOpen"); await t.wait()
    check("bez ciklusa" in (await t.pg.inner_text("#phase")).lower(), "nije prešao na rad bez ciklusa")
    k = await t.ev("S.mezociklusi.find(c=>c.id==='m1').kraj")
    check(bool(k), "završeni ciklus nema datum kraja")
    await t.new_cycle("p1")
    names = await t.ev("S.mezociklusi.map(c=>c.naziv).join(',')")
    check(names.endswith("M2"), f"naziv novog ciklusa pogrešan: {names}")

@test
async def program_switch_midweek(t: Ctx):
    await t.setup(); await t.new_cycle("p1")
    await t.start_workout("Upper A"); await t.set_row(0, 0, 50, 8); await t.finish(); await t.close()
    await t.ev("startOpenPeriod(PROG().find(p=>p.id==='p2'));render()")
    plan = await t.ev("weeklyPlanIds().map(id=>cleanWorkoutName(SAB().find(s=>s.id===id).naziv)).join(',')")
    check(plan == "Full B,Full B", f"plan sedmice ne prati novi program: {plan}")
    vol = json.loads(await t.ev("JSON.stringify(weeklyGroupVolume(iso(new Date()),null))"))
    check(any(r["g"] == "Grudi" and r["done"] == 1 for r in vol), f"odrađeni volumen prethodnog programa izgubljen: {vol}")
    await t.new_cycle("p1")
    st = await t.ev("weeklyPlanIds().map(id=>plannedWorkoutStatus(id)).join(',')")
    check(st.startswith("done"), f"već odrađen Upper A nije priznat posle prelaska: {st}")

@test
async def archived_workouts_and_frozen_past_weeks(t: Ctx):
    await t.setup()
    await t.ev("""()=>{const p=PROG().find(x=>x.id==='p1');const d=new Date(monday(iso(new Date()))+'T00:00:00');d.setDate(d.getDate()-7);window.pw=iso(d);startOpenPeriod(p,pw);
      const c=activeCycle(),sab=c.sabloni[0];sesija={datum:pw,sabId:sab.id,sessionId:'s1',startTs:Date.now(),stavke:sab.stavke.map(s=>({vezbaId:s.vezbaId,plan:s.b,pon:s.pon,odmor:'',unosi:[{kg:'50',pon:'8',done:true}]}))};finishWorkout(sab);closeDlg()}""")
    past = "JSON.stringify(groupFromSub(planPoPodgrupi(weeklyPlanIds(pw),faza(1,activeCycle()),workoutsForWeek(pw,true))))"
    before = await t.ev(past)
    await t.ev("LIB().find(w=>w.id==='u').stavke[0].b=5;PROG().find(p=>p.id==='p1').treningIds=['u'];save();render()")
    check(await t.ev(past) == before, "izmjena programa je promijenila plan prošle sedmice")
    check(await t.ev("workoutsForWeek(monday(iso(new Date()))).length") == 1, "uklonjeni trening se i dalje nudi")
    check(await t.ev("S.dnevnik.every(l=>!l.sabId||activeCycle().sabloni.some(s=>s.id===l.sabId))"), "istorija je izgubila vezu sa uklonjenim treningom")
    await t.go("vise", "{mc:activeCycle().id}")
    check("1× nedeljno" in await t.pg.inner_text("#view"), "arhivirani trening se broji u programu")

@test
async def program_copy_only_after_save(t: Ctx):
    await t.setup()
    before = await t.ev("LIB().length+'/'+PROG().length")
    await t.ev("programLibraryDialog()"); await t.wait(); await t.pg.click('[data-dupprog="p1"]'); await t.wait(200)
    await t.pg.click("#pCancel"); await t.wait()
    check(await t.ev("LIB().length+'/'+PROG().length") == before, "otkazana kopija je ostala sačuvana")
    await t.ev("programLibraryDialog()"); await t.wait(); await t.pg.click('[data-dupprog="p1"]'); await t.wait(200)
    t.pg.remove_listener("dialog", t._dlg); t.pg.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
    await t.pg.click("#pSave"); await t.wait(); await t.close()
    p = json.loads(await t.ev("JSON.stringify(PROG().slice(-1)[0].treningIds.map(id=>LIB().find(w=>w.id===id).naziv))"))
    check(p == ["Upper A — kopija", "Lower A — kopija"], f"kopija programa neispravna: {p}")

@test
async def library_import_without_duplicates(t: Ctx):
    await t.setup()
    pkg = await t.ev("JSON.stringify(libraryPackage())")
    r1 = json.loads(await t.ev(f"JSON.stringify(importLibrary(JSON.parse({json.dumps(pkg)})))"))
    check(r1["nw"] == 0 and r1["np"] == 0, f"ponovljen uvoz pravi duplikate: {r1}")
    r2 = json.loads(await t.ev(f"(()=>{{const k=JSON.parse({json.dumps(pkg)});k.treninzi[0].stavke[0].odmor='5 min';return JSON.stringify(importLibrary(k))}})()"))
    check(r2["nw"] == 1, f"izmijenjen odmor nije prepoznat kao drugačiji trening: {r2}")

@test
async def cycle_analytics(t: Ctx):
    await t.setup()
    await t.ev("""()=>{const n=x=>S.vezbe.find(v=>v.naziv===x).id;const c={id:'m1',naziv:'M1',pocetak:'2026-10-05',trajanje:6,nedelje:weekPreset(6),deloadPct:60,status:'završen',sourceProgramId:'p1',programNaziv:'UL',progresija:{midAdd:1,peakAdd:2},sabloni:librarySnapshot(['u','l'],{midAdd:1,peakAdd:2})};S.mezociklusi=[c];S.aktivniMezociklusId='m1';
      const v=n('Machine Chest Press');[['2026-10-06',60,8],['2026-10-20',65,9],['2026-11-03',70,8],['2026-11-11',50,8]].forEach(([d,kg,r])=>S.dnevnik.push({id:uid(),datum:d,vezbaId:v,serije:1,pon:r,kg,mezociklusId:'m1'}));save()}""")
    await t.go("vise", "{mc:'m1'}")
    txt = await t.pg.inner_text("#view")
    check("60×8 → 70×8" in txt.replace(" ", " "), f"napredak u ciklusu nije ispravan (deload nedjelja mora biti isključena)")
    check("prosjek" not in txt.split("NAPREDAK")[1][:200].lower(), "prosječni napredak ne treba prikazivati")

@test
async def backup_roundtrip(t: Ctx):
    await t.setup()
    await t.ev("""()=>{const d=new Date(monday(iso(new Date()))+'T00:00:00');d.setDate(d.getDate()-7);window.pw=iso(d);PROG().find(x=>x.id==='p1').treningIds=['u','l','u','l'];startOpenPeriod(PROG().find(x=>x.id==='p1'),pw);
      const fin=(date,i)=>{const c=activeCycle(),sab=c.sabloni[i];sesija={datum:date,sabId:sab.id,sessionId:'s'+Math.random(),startTs:Date.now(),stavke:sab.stavke.map(s=>({vezbaId:s.vezbaId,plan:s.b,pon:s.pon,odmor:'',unosi:[{kg:'60',pon:'8',done:true,nap:'test',rir:'2'},{kg:'60',pon:'12',done:true,tip:'myo',mini:'4+4+3'}]}))};finishWorkout(sab);closeDlg()};
      fin(pw,0);fin(pw,1);fin(iso(new Date()),0);LIB().find(w=>w.id==='u').stavke[0].b=5;PROG().find(x=>x.id==='p1').treningIds=['u','l','u'];save();render()}""")
    await t.pg.reload(); await t.wait(500); await t.close()   # startup migrations run on both sides
    view = """JSON.stringify({ime:S.ime,logs:S.dnevnik,periods:S.mezociklusi,lib:LIB(),prog:PROG(),auto:S.sedmicniPlanAuto,status:S.sedmicniStatus,rec:S.treningRekapitulacije,
      week:weeklyPlanIds(monday(iso(new Date())),activeCycle()).map(id=>plannedWorkoutStatus(id))})"""
    v1 = await t.ev(view)
    check(await t.ev("activeCycle().otvoren&&activeCycle().trajanje==null"), "pokretanje aplikacije je periodu bez ciklusa dodijelilo trajanje")
    await t.go("vise")
    async with t.pg.expect_download() as d: await t.pg.click("#exp")
    f = TMP / "backup.json"; await (await d.value).save_as(f)
    # fresh browser profile = new phone
    ctx2 = await t.browser.new_context(viewport={"width": 390, "height": 844})
    p2 = await ctx2.new_page(); p2.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await p2.goto(APP); await p2.wait_for_timeout(400); await p2.evaluate("closeDlg();go('vise')"); await p2.wait_for_timeout(150)
    await p2.set_input_files("#impF", str(f)); await p2.wait_for_timeout(500)
    v2 = await p2.evaluate(view)
    await ctx2.close()
    a, b = json.loads(v1), json.loads(v2)
    diff = [k for k in a if a[k] != b[k]]
    check(not diff, f"rezervna kopija nije vratila identično stanje: {diff}")

@test
async def all_screens_render(t: Ctx):
    await t.setup(); await t.new_cycle("p1")
    await t.start_workout("Upper A"); await t.set_row(0, 0, 50, 8); await t.finish(); await t.close()
    for tab in ["danas", "pregled", "program", "vezbe", "vise"]: await t.go(tab)
    for m in ["sedmica", "mezociklus", "vezba", "tijelo"]: await t.ev(f"pregledMode='{m}';go('pregled')"); await t.wait()
    await t.ev("detaljVezbe(S.dnevnik[0].vezbaId)"); await t.wait()
    await t.ev("detaljTreninga(S.dnevnik[0].sessionId)"); await t.wait()

@test
async def resume_unfinished_workout(t: Ctx):
    await t.setup(); await t.new_cycle("p1"); await t.start_workout("Upper A")
    await t.set_row(0, 0, 52.5, 9)
    await t.set_row(0, 1, 52.5, 8, confirm=False)
    await t.wait(900)                                 # session is saved with a short delay
    asked = []
    t.pg.remove_listener("dialog", t._dlg)
    t.pg.on("dialog", lambda d: (asked.append(d.message), asyncio.ensure_future(d.accept())))
    await t.pg.reload(); await t.wait(600)            # = app closed and opened again
    check(any("nezavršen trening" in a for a in asked), "nema ponude da se nastavi nezavršen trening")
    s = json.loads(await t.ev("JSON.stringify(sesija&&sesija.stavke[0].unosi.slice(0,2))"))
    check(s and s[0]["pon"] == "9" and s[0]["done"] is True and s[1]["pon"] == "8" and not s[1].get("done"), f"nastavljeni trening nije isti: {s}")
    await t.set_row(0, 1, 52.5, 8)                    # confirm it now
    await t.finish()
    check(await t.ev("S.dnevnik.length") == 2, "posle nastavka trening nije ispravno upisan")

@test
async def corrupted_backup_is_rejected(t: Ctx):
    await t.setup(); await t.new_cycle("p1")
    await t.start_workout("Upper A"); await t.set_row(0, 0, 50, 8); await t.finish(); await t.close()
    before = await t.ev("localStorage.getItem(KEY)")
    bad = {
        "nije_json.json": "{ovo nije json",
        "pogresna_struktura.json": json.dumps({"nesto": 1}),
        "buduca_verzija.json": json.dumps({"vezbe": [], "dnevnik": [], "schemaVersion": 999}),
        "biblioteka_umjesto_kopije.json": json.dumps({"tip": "my-training-biblioteka", "treninzi": []}),
    }
    await t.go("vise")
    for name, content in bad.items():
        f = TMP / name; f.write_text(content, encoding="utf-8")
        await t.pg.set_input_files("#impF", str(f)); await t.wait(400)
        check(await t.ev("localStorage.getItem(KEY)") == before, f"neispravan fajl {name} je promijenio podatke")
        await t.go("vise")
    check(await t.ev("S.dnevnik.length") == 1, "podaci su se promijenili posle neispravnog uvoza")

@test
async def upgrade_from_old_version_keeps_data(t: Ctx):
    try:
        old_html = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_VERSION_COMMIT}:index.html"], capture_output=True, check=True).stdout
    except Exception:
        print("         (preskočeno: stara verzija nije dostupna u git istoriji — za CI treba fetch-depth: 0)"); return
    old = ROOT / "tests" / ".old_index.html"; old.write_bytes(old_html)   # same folder = same file:// storage
    try:
        await t.ev("localStorage.clear()")                                 # start from the old version's own first run
        await t.pg.goto(old.as_uri()); await t.wait(600)
        await t.pg.evaluate("()=>{try{closeDlg()}catch(e){}}")
        snap = json.loads(await t.ev("JSON.stringify({logs:S.dnevnik.length,sets:S.dnevnik.reduce((a,l)=>a+Number(l.serije||1),0),cycles:(S.mezociklusi||[]).length,vezbe:S.vezbe.length})"))
        check(snap["logs"] > 0, "stara verzija nije napravila podatke")
        await t.pg.goto(APP); await t.wait(700)                             # new version reads the same storage
        await t.ev("()=>{try{closeDlg()}catch(e){}}")
        now = json.loads(await t.ev("JSON.stringify({logs:S.dnevnik.length,sets:S.dnevnik.reduce((a,l)=>a+Number(l.serije||1),0),cycles:S.mezociklusi.length,vezbe:S.vezbe.length,ime:S.ime,welcome:!!document.getElementById('wIme')})"))
        check(now["sets"] == snap["sets"], f"broj setova se promijenio pri ažuriranju: {snap} → {now}")
        check(now["cycles"] >= 1 and now["vezbe"] >= snap["vezbe"] - 20, f"izgubljeni ciklusi ili vježbe: {snap} → {now}")
        check(now["ime"] == "Ivan Lero" and not now["welcome"], "postojeći korisnik je tretiran kao novi")
        check(await t.ev("(S.tema||'classic')==='classic'&&getComputedStyle(document.body).backgroundColor==='rgb(23, 27, 32)'"), "postojeći korisnik nije zadržao dosadašnji izgled")
        for tab in ["danas", "pregled", "program", "vezbe", "vise"]: await t.go(tab)
    finally:
        old.unlink(missing_ok=True)

@test
async def offline_start_and_use(t: Ctx):
    srv, url = serve_repo()
    try:
        await t.pg.goto(url); await t.wait(800)
        await t.ev("navigator.serviceWorker.ready.then(()=>true)")
        await t.pg.reload(); await t.wait(800)                             # second load fills the cache
        await t.ev("()=>{try{closeDlg()}catch(e){}}")
        await t.setup(); await t.new_cycle("p1")
        await t.pg.context.set_offline(True)
        await t.pg.reload(); await t.wait(2500)                            # offline start (sw waits up to 1.5 s for network)
        check(await t.ev("typeof S==='object'&&S.mezociklusi.length===1"), "aplikacija se nije pokrenula bez interneta")
        await t.start_workout("Upper A"); await t.set_row(0, 0, 50, 8); await t.finish(); await t.close()
        check(await t.ev("S.dnevnik.length") == 1, "trening bez interneta nije sačuvan")
    finally:
        await t.pg.context.set_offline(False); srv.shutdown()

@test
async def week_and_year_change(t: Ctx):
    await t.pg.clock.set_fixed_time(datetime.datetime(2026, 12, 30, 10, 0))   # Wednesday
    await t.pg.reload(); await t.wait(500); await t.ev("()=>{try{closeDlg()}catch(e){}}")
    await t.setup(); await t.ev("startOpenPeriod(PROG().find(p=>p.id==='p1'));render()")
    check(await t.ev("monday(iso(new Date()))") == "2026-12-28", "pogrešan ponedjeljak u sedmici preko nove godine")
    await t.start_workout("Upper A"); await t.set_row(0, 0, 50, 8); await t.finish(); await t.close()
    check(await t.ev("weeklyPlanIds().map(id=>plannedWorkoutStatus(id)).join(',')") == "done,pending", "status u staroj godini")
    await t.pg.clock.set_fixed_time(datetime.datetime(2027, 1, 1, 10, 0))     # same week, new year
    await t.pg.reload(); await t.wait(500); await t.ev("()=>{try{closeDlg()}catch(e){}}")
    check(await t.ev("weeklyPlanIds().map(id=>plannedWorkoutStatus(id)).join(',')") == "done,pending", "nova godina u istoj sedmici je resetovala status")
    await t.pg.clock.set_fixed_time(datetime.datetime(2027, 1, 4, 10, 0))     # Monday, new week
    await t.pg.reload(); await t.wait(500); await t.ev("()=>{try{closeDlg()}catch(e){}}")
    check(await t.ev("pon0") == "2027-01-04", "nova sedmica nije prepoznata")
    check(await t.ev("weeklyPlanIds().map(id=>plannedWorkoutStatus(id)).join(',')") == "pending,pending", "nova sedmica nije počela iz početka")
    check(await t.ev("cikNedelja(iso(new Date()),activeCycle())") == 2, "broj sedmice perioda preko nove godine je pogrešan")
    check(await t.ev("frozenWeek('2026-12-28',activeCycle())!==null"), "prošla sedmica (stara godina) nije zamrznuta")
    for tab in ["danas", "pregled", "vise"]: await t.go(tab)

@test
async def themes_apply_and_persist(t: Ctx):
    check(await t.ev("S.tema") == "lightStone", "novi korisnik ne dobija Light Stone")
    await t.pg.fill("#wIme", "Ana"); await t.pg.click("#wOk"); await t.wait()
    bg = await t.ev("getComputedStyle(document.body).backgroundColor")
    check(bg == "rgb(236, 234, 228)", f"Light Stone pozadina nije primijenjena: {bg}")
    await t.go("vise")
    await t.pg.click('[data-theme="graphite"]'); await t.wait()
    check(await t.ev("S.tema") == "graphite" and await t.ev("localStorage.getItem('trening_tema')") == "graphite", "izbor teme nije sačuvan")
    await t.pg.reload(); await t.wait(500)
    check(await t.ev("getComputedStyle(document.body).backgroundColor") == "rgb(17, 19, 21)", "tema se nije zadržala posle ponovnog pokretanja")
    await t.go("vise"); await t.pg.click('[data-theme="classic"]'); await t.wait()
    check(await t.ev("getComputedStyle(document.body).backgroundColor") == "rgb(23, 27, 32)", "povratak na Classic ne radi")
    check(await t.ev("getComputedStyle(document.documentElement).getPropertyValue('--amber').trim()") == "#D9A441", "Classic nije vratio originalne boje")

# ---------------------------------------------------------------- runner

async def run_one(browser, fn):
    ctx = await browser.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True)
    page = await ctx.new_page(); errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    t = Ctx(page, errors); t.browser = browser
    t._dlg = lambda d: asyncio.ensure_future(d.accept())
    page.on("dialog", t._dlg)
    await page.goto(APP); await page.wait_for_timeout(400)
    try:
        await fn(t)
        if errors: raise AssertionError("JS greške u aplikaciji: " + " | ".join(errors))
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}" + ("" if isinstance(e, AssertionError) else "\n" + traceback.format_exc(limit=2))
    finally:
        await ctx.close()

async def main():
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    sel = [f for f in TESTS if flt in f.__name__]
    async with async_playwright() as p:
        engine = os.environ.get("BROWSER", "chromium")
        kw = {} if engine == "webkit" else {"args": ["--no-sandbox"]}
        if engine == "chromium" and os.environ.get("CHROME_PATH"): kw["executable_path"] = os.environ["CHROME_PATH"]
        browser = await getattr(p, engine).launch(**kw)
        print(f"Pregledač: {engine}\n")
        failed = 0
        for fn in sel:
            err = await run_one(browser, fn)
            print(("  OK   " if not err else "  FAIL ") + fn.__name__ + ("" if not err else "\n         " + err))
            failed += bool(err)
        await browser.close()
    print(f"\n{len(sel)-failed}/{len(sel)} testova prošlo")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    asyncio.run(main())
