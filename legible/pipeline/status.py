"""Deterministic rules: from Jev's per-sentence labels to one status per fact.

Only the parties' own procedural acts count as their position. Witness statements and exhibits are
evidence; expert reports and judgments are findings. Party keys and labels come from dossier/case.json.
"""
POS = {"affirms", "admits"}
PARTY_ACTS = {"assignation", "conclusions", "requete", "memoire", "lettre"}
FINDING_AUTHORS = {"expert", "court"}
UNCERTAIN_BELOW = 0.6


def short_labels(case):
    """{speaker key: short label}, from case['short'] or the text before ' (' / ','."""
    short = dict(case.get("short", {}))
    for k, v in case["speakers"].items():
        short.setdefault(k, v.split(" (")[0].split(",")[0].strip())
    return short


def _polarity(stance):
    return "pos" if stance in POS else ("neg" if stance == "denies" else None)


def _fr_date(d):
    return "/".join(reversed(d.split("-"))) if d and len(d) == 10 else (d or "")


def build_rows(case, docs, facts, labels, sentences):
    parties = list(case["parties"])  # [claimant, defendant]
    label = short_labels(case)
    meta = {d["meta"]["id"]: d["meta"] for d in docs}
    latest_brief = {}  # each party's last set of written submissions
    for m in sorted(meta.values(), key=lambda m: (m.get("date") or "", m.get("version", 1))):
        if m.get("author") in parties and m.get("type") in PARTY_ACTS:
            latest_brief[m["author"]] = m
    rows = {f["id"]: {**f, "by_party": {p: {"stance": None, "history": [], "reported": []} for p in parties},
                      "expert": [], "witnesses": [], "mentions": [], "flags": []} for f in facts}
    for lab in labels:
        row = rows.get(lab["fact"])
        if row is None:
            continue
        sid = lab["sid"]
        m = meta[sentences[sid]["doc"]]
        author, kind = m.get("author"), m.get("type")
        entry = {"sid": sid, "doc": m["id"], "date": m.get("date"), "version": m.get("version", 1),
                 "stance": lab["position"], "conf": lab["position_conf"]}
        row["mentions"].append(sid)
        if lab["position"] in POS | {"denies"}:
            if author in parties and kind in PARTY_ACTS:
                row["by_party"][author]["history"].append(entry)
            elif author in FINDING_AUTHORS:
                row["expert"].append({**entry, "who": author})
            else:
                row["witnesses"].append({**entry, "who": author})
        rep_who, rep_pos = lab["reported_speaker"], lab["reported_position"]
        if rep_who in parties and rep_pos in ("true", "false") and rep_who != author:
            row["by_party"][rep_who]["reported"].append(
                {"sid": sid, "doc": m["id"], "date": m.get("date"), "by": author,
                 "stance": "affirms" if rep_pos == "true" else "denies", "conf": lab["reported_position_conf"]})
    out = []
    for f in facts:
        row = rows[f["id"]]
        pol = {}
        for party, info in row["by_party"].items():
            hist = sorted(info["history"], key=lambda e: (e["date"] or "", e["version"]))
            info["history"] = hist
            if hist:
                info["stance"] = hist[-1]["stance"]
                pol[party] = _polarity(hist[-1]["stance"])
                seq = [(_polarity(e["stance"]), e) for e in hist]
                flips = [(a, b) for (pa, a), (pb, b) in zip(seq, seq[1:])
                         if pa and pb and pa != pb and a["doc"] != b["doc"]]
                if flips:
                    a, b = flips[-1]
                    row["flags"].append({"type": "version_change", "party": party, "from": a, "to": b,
                                         # a concession in written submissions may be a judicial admission
                                         "admission": a["stance"] == "admits"})
                last = latest_brief.get(party)
                if last and last["id"] not in {e["doc"] for e in hist} and (last.get("date") or "") > (hist[-1]["date"] or ""):
                    row["flags"].append({"type": "not_restated", "party": party, "last": hist[-1],
                                         "latest_doc": last["id"]})
            elif info["reported"]:
                info["stance"] = info["reported"][-1]["stance"]
                info["stance_source"] = "reported_by_opponent"
                pol[party] = _polarity(info["stance"])
        p1, p2 = (pol.get(p) for p in parties)
        vc = [fl for fl in row["flags"] if fl["type"] == "version_change"]
        verb = {"pos": "reconnaît", "neg": "conteste"}
        if vc:
            fl = vc[-1]
            row["status"] = "version_change"
            row["status_label"] = (f"Changement de version : {label[fl['party']]} "
                                   f"({verb[_polarity(fl['from']['stance'])]} le {_fr_date(fl['from']['date'])}, "
                                   f"{verb[_polarity(fl['to']['stance'])]} le {_fr_date(fl['to']['date'])})")
            if fl["admission"]:
                row["status_label"] += " · aveu judiciaire possible, en principe irrévocable (art. 1383-2 C. civ.)"
        elif p1 == "pos" and p2 == "pos":
            row["status"], row["status_label"] = "constant", "Constant : admis par les deux parties"
        elif {p1, p2} == {"pos", "neg"}:
            who, other = (parties[0], parties[1]) if p1 == "pos" else (parties[1], parties[0])
            row["status"], row["status_label"] = "disputed", f"Contesté : affirmé par {label[who]}, contesté par {label[other]}"
        elif "pos" in (p1, p2):
            who, other = (parties[0], parties[1]) if p1 == "pos" else (parties[1], parties[0])
            if row["by_party"][who]["stance"] == "admits":  # a concession, not a claim: it is established
                row["status"], row["status_label"] = "admitted", f"Reconnu par {label[who]}"
            else:
                row["status"], row["status_label"] = "alleged", f"Allégué par {label[who]}, sans réponse de {label[other]}"
        elif "neg" in (p1, p2):
            who = parties[0] if p1 == "neg" else parties[1]
            row["status"], row["status_label"] = "denied", f"Nié par {label[who]}"
        elif row["expert"]:
            row["status"], row["status_label"] = "found_by_expert", f"Relevé par {label.get(row['expert'][-1]['who'], 'l’expert')}"
        elif row["witnesses"]:
            row["status"], row["status_label"] = "evidence_only", "Seulement dans les pièces"
        else:
            row["status"], row["status_label"] = "unclear", "À vérifier : position des parties non identifiée"
        exp = [e for e in row["expert"] if _polarity(e["stance"])]
        if exp:
            ep = _polarity(exp[-1]["stance"])
            for party, p in pol.items():
                if p and p != ep:
                    row["flags"].append({"type": "expert_contradicts", "party": party, "expert": exp[-1]})
            if ep == "pos" and row["status"] in ("disputed", "alleged", "denied"):
                row["flags"].append({"type": "expert_confirms", "expert": exp[-1]})
        wit = {}
        for w in row["witnesses"]:
            if _polarity(w["stance"]):
                wit.setdefault(_polarity(w["stance"]), []).append(w["who"])
        if len(wit) == 2:
            row["flags"].append({"type": "witnesses_disagree", "pos": wit["pos"], "neg": wit["neg"]})
        used = [e for info in row["by_party"].values() for e in info["history"]] + row["expert"] + row["witnesses"]
        low = [e for e in used if (e.get("conf") or 0) < UNCERTAIN_BELOW]
        if low:
            row["flags"].append({"type": "uncertain", "sids": [e["sid"] for e in low]})
        out.append(row)
    return out
