"""Genera el historial inicial (semilla) a partir de los archivos de data/raw.

Entradas (data/raw):
  - EquiposOrios.txt            exportación diaria de Orios (última toma por equipo, acentos dañados)
  - equipos.xls                 la misma exportación en UTF-16 (acentos correctos); se usa para reparar el .txt
  - 2024_Monitor_Status.xlsx    hoja "equipos vibraciones": tomas de 2021-2024 con componentes y síntomas
  - EquiposOriosRed_sin_macros.xlsx  hoja "Tiempo": estatus por equipo hasta 03/2025 (sin componentes)

Salidas (data/processed):
  - seed_equipos.json           un documento por equipo con su historial de tomas
  - cargas_seed.json            registro de los tres archivos de origen
  - repair.json                 diccionario palabra dañada -> palabra correcta (acentos)
  - originales/                 copias en texto de los archivos de origen (para "Ver formato original")

Uso:  python scripts/build_seed.py
"""
import json, re, pathlib, shutil
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/processed"
(OUT / "originales").mkdir(parents=True, exist_ok=True)

SRC_TXT, SRC_2024, SRC_TIEMPO = "c_seed_txt", "c_seed_2024", "c_seed_tiempo"


def norm(s):
    return re.sub(r"\s+", " ", str(s if pd.notna(s) else "")).strip()


def djb(s):
    """Mismo hash que djb() en src/template.html: id estable de equipo = hash(Equipo|Sección)."""
    h = 5381
    for ch in s:
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    return "e" + format(h, "x")


def pdt(s):
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", s.strip())
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}", f"{int(m[4] or 0):02d}:{m[5] or '00'}"


txt = pd.read_csv(RAW / "EquiposOrios.txt", sep="\t", encoding="utf-8", dtype=str).fillna("")
xls = pd.read_csv(RAW / "equipos.xls", sep="\t", encoding="utf-16-le", dtype=str).fillna("")

# 1) diccionario de reparación de acentos: compara el .txt dañado contra el .xls correcto, fila por fila
rep = {}
for c in txt.columns:
    for a, b in zip(txt[c], xls[c]):
        if "�" in a:
            wa, wb = re.findall(r"\S+", a), re.findall(r"\S+", b)
            if len(wa) == len(wb):
                for p, q in zip(wa, wb):
                    if "�" in p and p != q:
                        k = re.sub(r"^[^\w�]+|[^\w�]+$", "", p)
                        v = re.sub(r"^[^\wÀ-ſ]+|[^\wÀ-ſ]+$", "", q)
                        if k and v and len(k) == len(v):
                            rep[k] = v
json.dump(rep, open(OUT / "repair.json", "w"), ensure_ascii=False, indent=1)

# 2) toma actual (texto correcto del .xls + fecha del .txt), sin filas duplicadas
cur = xls.copy()
cur["Fecha monitoreo"] = txt["Fecha monitoreo"]
cur = cur.drop_duplicates()
eqs = {}


def toma(e, f, h, st, act, src):
    for t in e["hist"]:
        if t["f"] == f:
            return t
    t = dict(f=f, h=h, e=st, a=act, comp=[], src=src)
    e["hist"].append(t)
    return t


for _, r in cur.iterrows():
    eq, sec = norm(r.Equipo), norm(r.Seccion)
    did = djb(eq + "|" + sec)
    f, h = pdt(r["Fecha monitoreo"])
    e = eqs.setdefault(did, dict(id=did, equipo=eq, seccion=sec, area=norm(r.Area), linea=norm(r.Linea), planta=norm(r.Planta),
                                 activo=r.EstaActivo.strip() == "Si", estatus=r.Estatus.strip(), fecha=f, hora=h, comp=[], hist=[]))
    c = dict(c=norm(r["Componente/Union"]), s=norm(r.Sintoma), r=norm(r.Recomendacion), k=norm(r["Comentarios del Analista"]))
    if c not in e["comp"]:
        e["comp"].append(c)
    t = toma(e, f, h, e["estatus"], e["activo"], SRC_TXT)
    if c not in t["comp"]:
        t["comp"].append(c)

byname = {}
for e in eqs.values():
    byname.setdefault(e["equipo"], []).append(e)

# 3) tomas de 2021-2024 con detalle
v = pd.read_excel(RAW / "2024_Monitor_Status.xlsx", sheet_name="equipos vibraciones").drop_duplicates()
for _, r in v.iterrows():
    did = djb(norm(r.Equipo) + "|" + norm(r.Seccion))
    if did not in eqs:
        continue
    f, h = r["Fecha monitoreo"].strftime("%Y-%m-%d"), r["Fecha monitoreo"].strftime("%H:%M")
    t = toma(eqs[did], f, h, norm(r.Estatus), norm(r.EstaActivo) == "Si", SRC_2024)
    c = dict(c=norm(r["Componente/Union"]), s=norm(r.Sintoma), r=norm(r.Recomendacion), k=norm(r["Comentarios del Analista"]))
    if t["src"] == SRC_2024 and c not in t["comp"]:
        t["comp"].append(c)

# 4) hoja Tiempo: solo estatus (sin sección; se usa solo si el nombre del equipo es único)
tm = pd.read_excel(RAW / "EquiposOriosRed_sin_macros.xlsx", sheet_name="Tiempo", header=3).dropna(subset=["Equipo"])
for _, r in tm.drop_duplicates(["Equipo", "Fecha monitoreo"]).iterrows():
    L = byname.get(norm(r.Equipo), [])
    if len(L) == 1:
        f, h = r["Fecha monitoreo"].strftime("%Y-%m-%d"), r["Fecha monitoreo"].strftime("%H:%M")
        toma(L[0], f, h, norm(r.Estatus), None, SRC_TIEMPO)

for e in eqs.values():
    e["hist"].sort(key=lambda t: t["f"])
docs = list(eqs.values())
json.dump(docs, open(OUT / "seed_equipos.json", "w"), ensure_ascii=False)

# 5) copias de los originales en texto
shutil.copy(RAW / "EquiposOrios.txt", OUT / "originales/EquiposOrios_2026-10-15.txt")
v.to_csv(OUT / "originales/2024_Monitor_Status_equipos_vibraciones.csv", index=False, encoding="utf-8-sig")
tm.to_csv(OUT / "originales/EquiposOriosRed_hoja_Tiempo.csv", index=False, encoding="utf-8-sig")

cargas = [
    dict(id=SRC_TXT, ts=1792694253825, archivo="EquiposOrios.txt (corte 15/10/2026)", fname="EquiposOrios_2026-10-15.txt", corte="2026-10-15",
         equipos=len(docs), filas=len(txt), duplicados=int(len(xls) - len(xls.drop_duplicates())), nuevas=len(docs), empeoraron=[]),
    dict(id=SRC_2024, ts=1792694253000, archivo="2024_Monitor_Status.xlsx · hoja equipos vibraciones", fname="2024_Monitor_Status_equipos_vibraciones.csv",
         corte=v["Fecha monitoreo"].max().strftime("%Y-%m-%d"), filas=len(v), empeoraron=[]),
    dict(id=SRC_TIEMPO, ts=1792694252000, archivo="EquiposOriosRed.xlsm · hoja Tiempo", fname="EquiposOriosRed_hoja_Tiempo.csv",
         corte=tm["Fecha monitoreo"].max().strftime("%Y-%m-%d"), filas=len(tm), empeoraron=[]),
]
json.dump(cargas, open(OUT / "cargas_seed.json", "w"), ensure_ascii=False, indent=1)
print(f"{len(docs)} equipos, {sum(len(d['hist']) for d in docs)} tomas, {len(rep)} palabras reparadas")


# ---------------------------------------------------------------------------------------------------------------
# MOTORES: "GDL - Pruebas Motores" (hoja Indice + una hoja por motor). Misma lógica que parsePruebas() en
# src/template.html: si cambias una, cambia la otra (tests/test_pagina.py verifica que den lo mismo).
# ---------------------------------------------------------------------------------------------------------------
import datetime, math, unicodedata
import openpyxl

MOT_FILE = RAW / "GDL - Pruebas Motores - Prueba_v2_sin_macros.xlsx"
ESTADO = {"normal": "DL", "n": "DL", "precaucion": "P2", "p": "P2", "alarma": "P1", "a": "P1"}
RANK = {"DL": 0, "P2": 1, "P1": 2}
PB_COMP = ["Estator (CA) / Armadura (CD)", "Rotor (CA) / Campo (CD)"]


def nk(s):
    return re.sub(r"[^A-Za-z]", "", unicodedata.normalize("NFD", "" if s is None else str(s))).lower()


def sval(v):
    if v is None: return ""
    if isinstance(v, float) and v.is_integer(): return str(int(v))
    return str(v)


def num(v):
    if isinstance(v, bool): return None
    if isinstance(v, (int, float)): return v
    s = sval(v).replace(",", ".", 1).strip()
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def fmtn(v):
    n = num(v)
    if n is None: return sval(v).strip() or "—"
    r = math.floor(n * 100 + 0.5) / 100
    if float(r).is_integer(): return f"{int(r):,}"
    return f"{r:,.2f}".rstrip("0").rstrip(".")


def txt(v):
    s = re.sub(r"\s+", " ", sval(v))
    return re.sub(r"^[\s,]+|[\s,]+$", "", s).strip()


iso = lambda d: d.strftime("%Y-%m-%d")
fmtd = lambda f: f[8:10] + "/" + f[5:7] + "/" + f[0:4]
LIMITE = datetime.datetime.now() + datetime.timedelta(days=1)
SRC_MOT = "c_seed_mot"

wbm = openpyxl.load_workbook(MOT_FILE, data_only=True, read_only=True)
rows = [list(r) for r in wbm["Indice"].iter_rows(min_row=1, min_col=1, values_only=True)]
hi = next(i for i, r in enumerate(rows) if any(nk(x) == "motor" for x in r) and any(nk(x) == "hoja" for x in r))
H = [nk(x) for x in rows[hi]]
ci = lambda name, frm=0: H.index(name, frm) if name in H[frm:] else -1
cH, cM, cA, cT = ci("hoja"), ci("motor"), ci("area"), ci("tipo")
cF1 = next(i for i, h in enumerate(H) if h.startswith("fechadeultimaprueba"))
cF2 = next((i for i, h in enumerate(H) if i > cF1 and h.startswith("fechadeultimaprueba")), -1)
cCom, cOT, cEst, cPl = ci("comentarios"), ci("ot"), ci("estatus"), ci("planta")
cGen = -1
for j in range(cPl + 1, len(H)):
    vals = [nk(r[j]) for r in rows[hi + 1:] if j < len(r) and nk(r[j])]
    if len(vals) > 10 and all(v in ESTADO for v in vals):
        cGen = j; break
get = lambda r, j: r[j] if 0 <= j < len(r) else None

mot_eqs, pruebas, futuras = [], 0, 0
for r in rows[hi + 1:]:
    name, hoja = txt(get(r, cM)), sval(get(r, cH)).strip()
    if not name or hoja == "": continue
    if cPl >= 0 and get(r, cPl) and not re.search(r"guadalajara|gdl", str(get(r, cPl)), re.I): continue
    area = txt(get(r, cA)) or "Sin área"; area = area[0].upper() + area[1:]
    activo = not re.match(r"^no", txt(get(r, cEst)), re.I)
    base = dict(id=djb("pruebas-motor|" + hoja), equipo=name, seccion=area, area=area,
                linea=("Tipo " + txt(get(r, cT))) if get(r, cT) else "", planta=txt(get(r, cPl)) or "Guadalajara", activo=activo)
    by = {}
    if hoja in wbm.sheetnames:
        R = [list(x) for x in wbm[hoja].iter_rows(min_row=1, max_row=110, min_col=1, values_only=True)]
        g = lambda x, j: x[j] if j < len(x) else None
        for bi, o in enumerate((0, 36)):
            lp = num(g(R[12], 12 + o)) if len(R) > 12 else None; lp = 100 if lp is None else lp
            la = num(g(R[13], 12 + o)) if len(R) > 13 else None; la = 75 if la is None else la
            lps, las = fmtn(lp), fmtn(la)
            for x in R[18:110]:
                d = g(x, 9 + o)
                if not isinstance(d, datetime.datetime) or d.year < 1990: continue  # 30/12/1899 = celda en cero
                if d > LIMITE: futuras += 1; continue
                Rv = num(g(x, 28 + o))
                if Rv is None: Rv = num(g(x, 12 + o))
                if Rv is None: continue
                pruebas += 1
                e = "P1" if Rv < la else "P2" if Rv < lp else "DL"
                f = iso(d)
                s = "" if e == "DL" else f"Resistencia de aislamiento {'en alarma' if e == 'P1' else 'en precaución'}: {fmtn(Rv)} MΩ (precaución < {lps} MΩ, alarma < {las} MΩ)"
                k = " · ".join(p for p in [f"Prueba {fmtd(f)}: aislamiento {fmtn(Rv)} MΩ · IA {fmtn(g(x, 30 + o))} · IP {fmtn(g(x, 32 + o))}",
                                          ("equipo " + txt(g(x, 8 + o))) if txt(g(x, 8 + o)) else "", txt(g(x, 34 + o)),
                                          ("OT " + txt(g(x, 35 + o))) if txt(g(x, 35 + o)) else ""] if p)
                tm = by.setdefault(f, dict(f=f, e=e, comp=[]))
                if RANK[e] > RANK[tm["e"]]: tm["e"] = e
                tm["comp"].append(dict(c=PB_COMP[bi], s=s, r="", k=k))
    blocks = []
    for c, bi in [(cF1, 0), (cF2, 1)]:
        if c < 0: continue
        d = get(r, c)
        if not isinstance(d, datetime.datetime) or d.year < 1990: continue
        if d > LIMITE: futuras += 1; continue
        blocks.append(dict(bi=bi, d=d, R=get(r, c + 1), IP=get(r, c + 2), E=ESTADO.get(nk(get(r, c + 3)), "")))
    gen = ESTADO.get(nk(get(r, cGen)), "") if cGen >= 0 else ""
    if not blocks and not by: continue
    fult = max(iso(b["d"]) for b in blocks) if blocks else max(by)
    coment = " · ".join(p for p in [txt(get(r, cCom)), ("OT " + txt(get(r, cOT))) if txt(get(r, cOT)) else ""] if p)
    if blocks:
        comp_act = []
        for b in blocks:
            e = b["E"] or "DL"; Rv = num(b["R"])
            s = "" if e == "DL" else (f"Resistencia de aislamiento {'en alarma' if e == 'P1' else 'en precaución'}: {fmtn(Rv)} MΩ" if Rv is not None
                                      else f"Estado {'Alarma' if e == 'P1' else 'Precaución'} según el índice (sin valor de resistencia)")
            comp_act.append(dict(c=PB_COMP[b["bi"]], s=s, r="", k=" · ".join(p for p in [f"Última prueba {fmtd(iso(b['d']))}: aislamiento {fmtn(b['R'])} MΩ · IP {fmtn(b['IP'])}", coment] if p)))
        states = [b["E"] or "DL" for b in blocks]
    else:
        comp_act = by.get(fult, {"comp": []})["comp"]; states = [by.get(fult, {"e": "DL"})["e"]]
    e_act = gen or max(states, key=lambda s: RANK[s])
    by[fult] = dict(f=fult, e=e_act, comp=comp_act)
    hist = [dict(f=t["f"], h="00:00", e=t["e"], a=activo, comp=t["comp"], src=SRC_MOT) for t in sorted(by.values(), key=lambda t: t["f"])]
    last = hist[-1]
    mot_eqs.append(dict(hist=hist, **base, estatus=last["e"], fecha=last["f"], hora="00:00", comp=last["comp"]))

json.dump(mot_eqs, open(OUT / "seed_motores.json", "w"), ensure_ascii=False)
json.dump([dict(id=SRC_MOT, ts=1793147000000, archivo="GDL - Pruebas Motores - Prueba_v2.xlsm", fname="GDL - Pruebas Motores - Prueba_v2.xlsx",
                corte=max(e["fecha"] for e in mot_eqs), equipos=len(mot_eqs), filas=pruebas, duplicados=0,
                nuevas=sum(len(e["hist"]) for e in mot_eqs), empeoraron=[])],
          open(OUT / "cargas_motores.json", "w"), ensure_ascii=False, indent=1)
print(f"motores: {len(mot_eqs)} equipos, {pruebas} pruebas, {sum(len(e['hist']) for e in mot_eqs)} tomas, {futuras} fechas a futuro ignoradas")


# ---------------------------------------------------------------------------------------------------------------
# PRUEBAS POR BLOQUES: "GDL - Pruebas Interruptores" y "GDL - Pruebas Transformadores" (hoja Indice + una hoja por equipo
# con varios bloques de prueba). Misma lógica que parseBloques() en src/template.html: si cambias una, cambia la otra.
# ---------------------------------------------------------------------------------------------------------------
LETRAS = re.compile(r"[A-Za-zÁÉÍÓÚáéíóú%]")


def est_bq(v):
    k = nk(v)
    if not k or k in ("noactivo", "vencido", "sinregistro"): return ""
    if k in ("buenestado", "ok"): return "DL"
    if k == "monitorear": return "P2"
    return "P1"


def cl(v):
    if isinstance(v, datetime.datetime): return fmtd(iso(v))
    return "" if v == 0 and not isinstance(v, bool) or v == "0" else txt(v)


def mv(v):
    if isinstance(v, bool): return txt(v)
    if isinstance(v, (int, float)):
        f = float(f"{v:.6g}")
        return str(int(f)) if f.is_integer() else repr(f)
    return txt(v)


def ok_name(v):
    t = txt(v)
    return t if LETRAS.search(t) and not t.endswith(":") and not re.fullmatch(r"(min|max|l[ií]mite)", t, re.I) else ""


def is_date(v):
    return isinstance(v, (datetime.datetime, datetime.date, datetime.time))


def parse_bloques(path, mid, src):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    rows = [list(r) for r in wb["Indice"].iter_rows(min_row=1, min_col=1, values_only=True)]
    hi = next(i for i, r in enumerate(rows) if any(nk(x) == "hoja" for x in r) and any(nk(x) == "nombre" for x in r))
    H = [nk(x) for x in rows[hi]]
    ci = lambda f: next((i for i, h in enumerate(H) if f(h)), -1)
    cH, cN, cU, cPl = ci(lambda h: h == "hoja"), ci(lambda h: h == "nombre"), ci(lambda h: h == "ubicacion"), ci(lambda h: h == "planta")
    cT = ci(lambda h: h == "tipotransformador")
    if cT < 0: cT = ci(lambda h: h == "tipo")
    cAct = ci(lambda h: h in ("estatusequipo", "estatusactivo"))
    nBq = sum(1 for h in H if h == "fecha") or 99
    get = lambda r, j: r[j] if 0 <= j < len(r) else None
    eqs, pruebas, futuras = [], 0, 0
    for r in rows[hi + 1:]:
        name, hoja = txt(get(r, cN)), txt(get(r, cH))
        if not name or not hoja or hoja == "0" or nk(hoja) == "ejemplo": continue
        if cPl >= 0 and get(r, cPl) and not re.search(r"guadalajara|gdl", str(get(r, cPl)), re.I): continue
        area = txt(get(r, cU)) or "Sin área"; area = area[0].upper() + area[1:]
        activo = not re.match(r"^no", txt(get(r, cAct)), re.I)
        base = dict(id=djb("bloques-" + mid + "|" + hoja), equipo=name, seccion=area, area=area,
                    linea=txt(get(r, cT)) if cT >= 0 and txt(get(r, cT)) else "", planta=txt(get(r, cPl)) or "Guadalajara", activo=activo)
        if hoja not in wb.sheetnames: continue
        ws = wb[hoja]
        R = [list(x) for x in ws.iter_rows(min_row=1, max_row=32, min_col=1, values_only=True)]
        while len(R) < 32: R.append([])
        g = lambda x, j: x[j] if 0 <= j < len(x) else None
        r6, r14, r15 = R[5], R[13], R[14]
        fechas = []
        for j, v in enumerate(r14):
            k = nk(v)
            if k.startswith("fechade") and ("prueba" in k or "muestra" in k) and len(fechas) < nBq: fechas.append(j)
        blocks = []
        for i, cf in enumerate(fechas):
            fin = fechas[i + 1] if i + 1 < len(fechas) else len(r15)
            ce = next((j for j in range(cf + 1, fin) if re.match(r"^(estado|recomendacion)", nk(g(r15, j)))), -1)
            if ce < 0: continue
            find = lambda pat: next((j for j in range(ce + 1, min(fin, ce + 6)) if re.match(pat, nk(g(r15, j)))), -1)
            blocks.append(dict(t=txt(g(r6, cf - 1)) or txt(g(r6, cf)) or f"Prueba {i + 1}", cf=cf, ce=ce,
                               co=find(r"^observ"), ca=find(r"^accion"), cot=find(r"^ot$")))
        tests = []
        for bi, b in enumerate(blocks):
            for x in R[15:32]:
                d = g(x, b["cf"])
                if not isinstance(d, datetime.datetime) or d.year < 1990: continue
                if d > LIMITE: futuras += 1; continue
                est = txt(g(x, b["ce"])); e = est_bq(est)
                if not e: continue
                pruebas += 1
                meds, nOK, grp = [], 0, ""
                for j in range(b["cf"] + 2, b["ce"]):
                    nm = ok_name(g(R[11], j)) or ok_name(g(R[10], j)) or ok_name(g(R[9], j))
                    if nm: grp = nm
                    sub = txt(g(r14, j))
                    label = ((nm or (grp if sub else "")) + (" " + sub if sub else "")).strip()
                    v = g(x, j)
                    if is_date(v): continue
                    s = mv(v)
                    if not s or s == "-" or nk(s) == "na": continue
                    if nk(s) == "ok": nOK += 1; continue
                    if not label: continue
                    u = txt(g(r15, j))
                    meds.append(f"{label} {s}" + (" " + u if u else ""))
                if nOK: meds.insert(0, f"{nOK} puntos OK")
                tests.append(dict(f=iso(d), bi=bi, e=e, est=est, cia=cl(g(x, b["cf"] - 1)), obs=cl(g(x, b["co"])) if b["co"] >= 0 else "",
                                  acc=cl(g(x, b["ca"])) if b["ca"] >= 0 else "", ot=cl(g(x, b["cot"])) if b["cot"] >= 0 else "", meds=meds[:16]))
        if not tests: continue
        tests.sort(key=lambda t: (t["f"], t["bi"]))
        last, hist = {}, []
        for f in dict.fromkeys(t["f"] for t in tests):
            for t in tests:
                if t["f"] == f: last[t["bi"]] = t
            comp = []
            for bi in sorted(last):
                t = last[bi]
                k = " · ".join(p for p in [("Prueba " if t["f"] == f else "Última prueba ") + fmtd(t["f"]) + (" · " + t["cia"] if t["cia"] else ""),
                                           *t["meds"], t["obs"], ("OT " + t["ot"]) if t["ot"] else ""] if p)
                comp.append(dict(c=blocks[bi]["t"], s="" if t["e"] == "DL" else t["est"], r=t["acc"], k=k))
            e = max((t["e"] for t in last.values()), key=lambda s: RANK[s], default="DL")
            hist.append(dict(f=f, h="00:00", e=e, a=activo, comp=comp, src=src))
        last_t = hist[-1]
        eqs.append(dict(hist=hist, **base, estatus=last_t["e"], fecha=last_t["f"], hora="00:00", comp=last_t["comp"]))
    return eqs, pruebas, futuras


for mid, fname, orig in [("int", "GDL - Pruebas Interruptores_v2_sin_macros.xlsx", "GDL - Pruebas Interruptores_v2.xlsm"),
                         ("tra", "GDL - Pruebas Transformadores_v1_sin_macros.xlsx", "GDL - Pruebas Transformadores_v1.xlsm")]:
    src = "c_seed_" + mid
    eqs, pr, fut = parse_bloques(RAW / fname, mid, src)
    json.dump(eqs, open(OUT / f"seed_{mid}.json", "w"), ensure_ascii=False)
    json.dump([dict(id=src, ts=1793147000000, archivo=orig, fname=fname, corte=max(e["fecha"] for e in eqs), equipos=len(eqs), filas=pr,
                    duplicados=0, nuevas=sum(len(e["hist"]) for e in eqs), empeoraron=[])],
              open(OUT / f"cargas_{mid}.json", "w"), ensure_ascii=False, indent=1)
    print(f"{mid}: {len(eqs)} equipos, {pr} pruebas, {sum(len(e['hist']) for e in eqs)} tomas, {fut} fechas a futuro ignoradas")


# ---------------------------------------------------------------------------------------------------------------
# TRIBOLOGÍA: exportación de análisis de aceite de Mobil Serv (Signum), texto separado por "|".
# Misma lógica que parseSignum() en src/template.html: si cambias una, cambia la otra.
# ---------------------------------------------------------------------------------------------------------------
TRI_FILE = RAW / "Tribologia.txt"
SIG_ST = {"alert": "P1", "caution": "P2", "normal": "DL"}
SIG_RV = {"alert": "alerta", "caution": "precaución", "normal": "normal"}
SIG_APP = {"geardrive": "Reductor", "circulatingsystem": "Sistema de circulación", "hydraulic": "Hidráulico", "compressor": "Compresor"}
SIG_RT = [("contaminationrating", "Contaminación"), ("equipmentrating", "Desgaste del equipo"), ("oilrating", "Condición del aceite")]
LAB_MET = [("Fe", "feiron"), ("Cu", "cucopper"), ("Pb", "pblead"), ("Cr", "crchromium"), ("Al", "alaluminum"), ("Sn", "sntin"), ("Ni", "ninickel"),
           ("Ag", "agsilver"), ("Ti", "tititanium"), ("V", "vvanadium"), ("Mn", "mnmanganese"), ("Si", "sisilicon"), ("Na", "nasodium"),
           ("K", "kpotassium"), ("Ca", "cacalcium"), ("Mg", "mgmagnesium"), ("Zn", "znzinc"), ("P", "pphosphorus"), ("Mo", "momolybdenum"),
           ("B", "bboron"), ("Ba", "babarium")]
LAB_PROP = [("v40", "viscosity40c"), ("v100", "viscosity100c"), ("h2o", "waterhotplate"), ("tan", "tanmgkohgm")]
SIG_BOILER = re.compile(r"\s*(Contacte a su representante de ExxonMobil[^.]*\.|Para mayor información contacte a su representante[^.]*\.)", re.I)


def ws_(v):
    t = "" if v is None else str(v)
    if re.search("[ÃÂ]", t):   # acentos dañados ("acciÃ³n", "CONDICIÃ“N"), como moji() en la página
        try:
            raw = bytes(ord(ch) if ord(ch) < 256 else ch.encode("cp1252")[0] for ch in t)
            t = raw.decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError): pass
    t = re.sub(r"\s+", " ", t).strip()
    if re.fullmatch(r"-?\d+\.\d+", t):   # "0.40" (txt) y 0.4 (Excel) quedan igual, como String(Number(t)) en la página
        f = float(t); t = str(int(f)) if f.is_integer() else repr(f)
    return t


def cap(t):
    return t[0].upper() + t[1:] if t else t


def parse_signum(text):
    rows = [l.split("|") for l in re.split(r"\f?\r?\n", text.lstrip("﻿")) if l.strip()]
    is_head = lambda r: "signumnumber" in [nk(x) for x in r] and "overallstatus" in [nk(x) for x in r]
    hi = next(i for i, r in enumerate(rows) if is_head(r))
    H = [ws_(x) for x in rows[hi]]; K = [nk(x) for x in H]
    ci = lambda k: K.index(k) if k in K else -1
    cName, cSig, cUnit, cDesc, cApp, cLub = ci("name"), ci("signumnumber"), ci("unitid"), ci("description"), ci("application"), ci("registeredlubricant")
    cSt, cSid, cDate, cOv, cCom, cAge, cAgeU = ci("samplepointstatus"), ci("sampleid"), ci("datesampled"), ci("overallstatus"), ci("comments"), ci("oilage"), ci("oilageuom")
    skip = {"overallstatus", "sampleresult", *[k for k, _ in SIG_RT]}
    flag_cols = [j for j, k in enumerate(K) if k == "status" and j + 1 < len(K) and K[j + 1] not in skip]
    g = lambda r, j: r[j] if 0 <= j < len(r) else ""
    KD = [re.sub(r"[^A-Za-z0-9]", "", unicodedata.normalize("NFD", h)).lower() for h in H]   # conserva dígitos, como KD en la página
    lab_cols = [(n, [j for j, x in enumerate(KD) if x == k]) for n, k in LAB_PROP + LAB_MET]
    cLt = ci("lubricanttested")
    props = {n for n, _ in LAB_PROP}
    hoy = iso(datetime.datetime.now() + datetime.timedelta(days=1))
    seen, tomas, filas = set(), [], 0
    for r in rows[hi + 1:]:
        if len(r) < 5 or not any(ws_(x) for x in r): continue
        filas += 1
        sig = ws_(g(r, cSig)); m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", str(g(r, cDate)))
        f = f"{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}" if m else ""
        e = SIG_ST.get(nk(g(r, cOv)))
        nm = ws_(g(r, cName))
        if not sig or not f or not e or f > hoy or (re.search("planta", nm, re.I) and not re.search("guadalajara", nm, re.I)): continue
        sid = ws_(g(r, cSid)) or sig + "|" + f
        if sid in seen: continue
        seen.add(sid)
        area = cap(ws_(g(r, cName)).split("/")[-1].strip().lower()) or "Sin área"
        desc, unit, app = ws_(g(r, cDesc)) or sig, ws_(g(r, cUnit)), ws_(g(r, cApp))
        flags = [f"{H[j + 1]} {ws_(g(r, j + 1))} ({'alerta' if g(r, j) == '*' else 'precaución'})" for j in flag_cols if g(r, j) in ("*", "+")]
        rat = " · ".join(f"{n}: {SIG_RV.get(nk(g(r, ci(k))), ws_(g(r, ci(k))))}" for k, n in SIG_RT if ci(k) >= 0 and ws_(g(r, ci(k))))
        resumen = " · ".join(p for p in [f"Muestra {fmtd(f)}" + (f" · ID {ws_(g(r, cSid))}" if ws_(g(r, cSid)) else ""),
                                         ("Lubricante " + ws_(g(r, cLub))) if ws_(g(r, cLub)) else "",
                                         f"Edad del aceite {ws_(g(r, cAge))} {ws_(g(r, cAgeU))}".strip() if ws_(g(r, cAge)) else "",
                                         rat, ("Fuera de límite: " + ", ".join(flags)) if flags else ""] if p)
        lab, met = {}, {}
        lub = ws_(g(r, cLt)) or ws_(g(r, cLub))
        if lub: lab["lub"] = lub
        for n, cols in lab_cols:
            j = next((j for j in cols if ws_(g(r, j)) != ""), None)
            if j is None: continue
            v = ws_(g(r, j))
            if n == "h2o": v = "No detectada" if re.match(r"^not", v, re.I) else "Detectada" if re.match(r"^det", v, re.I) else v
            fl = g(r, j - 1) if g(r, j - 1) in ("*", "+") else ""
            (lab if n in props else met)[n] = [v, fl]
        if met: lab["m"] = met
        comp = []
        if e != "DL":
            for sec0 in str(g(r, cCom)).split("@"):
                sec = ws_(sec0)
                if not sec: continue
                mm = re.match(r"^(.*?)\.(\s|$)", sec)
                head = mm[1] if mm else sec
                body = ws_(SIG_BOILER.sub("", sec[mm.end():] if mm else ""))
                d = re.match(r"^(.*?)\s*-\s*(.+)$", head)
                tipo, tema = (d[1], d[2].lower()) if d else ("", head.lower())
                if re.match(r"^no se requ", head, re.I): continue
                tl = re.sub(r"^precaucion", "precaución", re.sub(r"^accion", "acción", tipo.lower()))
                comp.append(dict(c=cap(tema), s=f"{cap(tl)}: {tema}" if tipo else cap(tema), r=body, k=""))
            if not comp:
                comp.append(dict(c="Análisis de aceite", s=("Fuera de límite: " + ", ".join(flags)) if flags else ("Alerta" if e == "P1" else "Precaución"), r="", k=""))
            comp[0]["k"] = resumen
            comp[0]["lab"] = lab
        else:
            comp = [dict(c="Análisis de aceite", s="", r="", k=resumen, lab=lab)]
        tomas.append(dict(id=djb("signum|" + sig), equipo=f"{desc} · {unit}" if unit and unit not in desc else desc, seccion=area, area=area,
                          linea=" · ".join(x for x in [SIG_APP.get(nk(app), app), lub] if x), planta="Guadalajara", activo=not re.match(r"^inact", ws_(g(r, cSt)), re.I),
                          estatus=e, fecha=f, hora="00:00", comp=comp))
    return tomas, filas


tri_tomas, tri_filas = parse_signum(open(TRI_FILE, encoding="utf-8-sig").read())
by_eq = {}
for t in sorted(tri_tomas, key=lambda t: t["fecha"]):
    by_eq.setdefault(t["id"], []).append(t)
tri_eqs = []
for tid, ts_ in by_eq.items():
    last = ts_[-1]
    hist = [dict(f=t["fecha"], h="00:00", e=t["estatus"], a=t["activo"], comp=t["comp"], src="c_seed_tri") for t in ts_]
    tri_eqs.append(dict(hist=hist, **{k: last[k] for k in ("id", "equipo", "seccion", "area", "linea", "planta", "activo", "estatus", "fecha", "hora", "comp")}))
json.dump(tri_eqs, open(OUT / "seed_tri.json", "w"), ensure_ascii=False)
json.dump([dict(id="c_seed_tri", ts=1794950000000, archivo="Tribologia.txt", fname="Tribologia.txt", corte=max(e["fecha"] for e in tri_eqs),
                equipos=len(tri_eqs), filas=tri_filas, duplicados=0, nuevas=len(tri_tomas), empeoraron=[])],
          open(OUT / "cargas_tri.json", "w"), ensure_ascii=False, indent=1)
print(f"tribología: {len(tri_eqs)} equipos, {len(tri_tomas)} muestras")
