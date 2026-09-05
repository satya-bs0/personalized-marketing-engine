"""
Generate data/golden_set.json with 50 hand-crafted evaluation examples.

30 should-pass (6 per lifecycle stage) + 20 should-fail (8 specific failure modes).
Run once: python scripts/generate_golden_set.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

OUT = Path(__file__).parent.parent / "data" / "golden_set.json"

MLR_TS = "2025-01-15T10:00:00+00:00"
DONOR_TS = "2025-01-01T00:00:00"
FORB = ["paraphrase", "rewrite", "expand"]
ALL_LC = ["new", "regular", "champion", "at_risk", "lapsed"]
ALL_RT = ["0-2wk", "3-5wk", "6-10wk", "11-20wk", "20wk+"]


# ---------------------------------------------------------------------------
# Block library (exact texts from seed_blocks.py)
# ---------------------------------------------------------------------------

def blk(bid, btype, text, tokens, lcs, rts, mlr_n):
    return {
        "block_id": bid, "block_type": btype, "version": 1,
        "approved_text": text, "safe_tokens": tokens,
        "segment_fit": {"lifecycle_stages": lcs, "recency_tiers": rts},
        "mlr_approval_id": f"MLR-2025-{mlr_n}",
        "mlr_approved_at": MLR_TS, "status": "approved",
        "forbidden_modifications": FORB, "created_at": MLR_TS,
    }


BLOCKS = {
    "subj_new":     blk("subject_new_welcome_v1", "subject",
                        "Welcome to the BioLife family, {first_name}",
                        ["first_name"], ["new"], ["0-2wk","3-5wk"], 1001),
    "subj_reg":     blk("subject_regular_appreciation_v1", "subject",
                        "Thank you for being there, {first_name}",
                        ["first_name"], ["regular"], ["0-2wk","3-5wk","6-10wk"], 1002),
    "subj_champ":   blk("subject_champion_milestone_v1", "subject",
                        "{first_name}, your dedication inspires us",
                        ["first_name"], ["champion"], ["0-2wk","3-5wk"], 1003),
    "subj_risk":    blk("subject_atrisk_warmthink_v1", "subject",
                        "We've been thinking of you, {first_name}",
                        ["first_name"], ["at_risk","lapsed"], ["6-10wk","11-20wk","20wk+"], 1004),
    "subj_univ":    blk("subject_universal_update_v1", "subject",
                        "A note from the BioLife team",
                        [], ALL_LC, ALL_RT, 1005),

    "open_new":     blk("opener_new_welcome_v1", "opener",
                        "Hi {first_name}, welcome to the BioLife community — we’re so glad you’re here and inspired by your choice to donate.",
                        ["first_name"], ["new"], ["0-2wk","3-5wk"], 1006),
    "open_reg":     blk("opener_regular_warm_v1", "opener",
                        "Hi {first_name}, your ongoing commitment to plasma donation continues to inspire us at {center_name}.",
                        ["first_name","center_name"], ["regular"], ["0-2wk","3-5wk","6-10wk"], 1007),
    "open_champ":   blk("opener_champion_recognition_v1", "opener",
                        "Hi {first_name}, your commitment is remarkable — {lifetime_donations} donations and counting at {center_name}.",
                        ["first_name","lifetime_donations","center_name"], ["champion"], ["0-2wk","3-5wk"], 1008),
    "open_risk":    blk("opener_atrisk_reconnect_v1", "opener",
                        "Hi {first_name}, we noticed it has been {weeks_since_last_donation} weeks since your last visit — we hope you’re doing well.",
                        ["first_name","weeks_since_last_donation"], ["at_risk"], ["6-10wk","11-20wk"], 1009),
    "open_lapsed":  blk("opener_lapsed_warmwelcome_v1", "opener",
                        "Hi {first_name}, we miss seeing you at {center_name} and wanted to reach out with a warm hello.",
                        ["first_name","center_name"], ["lapsed"], ["11-20wk","20wk+"], 1010),

    "imp_personal": blk("impact_personalized_v1", "impact",
                        "Your contributions have helped an estimated {estimated_patients_helped} patients receive life-saving therapies.",
                        ["estimated_patients_helped"], ALL_LC, ALL_RT, 1011),
    "imp_new":      blk("impact_new_first_v1", "impact",
                        "Even early donations make a lasting difference — plasma donations like yours help patients who depend on a consistent supply.",
                        [], ["new"], ["0-2wk","3-5wk"], 1012),
    "imp_champ":    blk("impact_champion_legacy_v1", "impact",
                        "With {lifetime_donations} donations, your legacy at {center_name} has helped an estimated {estimated_patients_helped} patients in need.",
                        ["lifetime_donations","center_name","estimated_patients_helped"], ["champion"], ["0-2wk","3-5wk"], 1013),
    "imp_risk":     blk("impact_atrisk_consistent_v1", "impact",
                        "Each donation contributes to a steady supply that patients rely on throughout the year — your commitment matters more than you know.",
                        [], ["at_risk","regular"], ["6-10wk","11-20wk"], 1014),
    "imp_lapsed":   blk("impact_lapsed_memory_v1", "impact",
                        "Your past donations have helped an estimated {estimated_patients_helped} patients — that generosity never goes unnoticed or forgotten.",
                        ["estimated_patients_helped"], ["lapsed"], ["11-20wk","20wk+"], 1015),

    "sp_comm":      blk("social_proof_community_v1", "social_proof",
                        "You are part of a dedicated community of donors at {center_name} who show up for patients time after time.",
                        ["center_name"], ALL_LC, ALL_RT, 1016),
    "sp_new":       blk("social_proof_new_joining_v1", "social_proof",
                        "Thousands of donors at BioLife centers have made the same commitment you have — you are joining something meaningful.",
                        [], ["new"], ["0-2wk","3-5wk"], 1017),
    "sp_champ":     blk("social_proof_champion_peers_v1", "social_proof",
                        "Donors with {lifetime_donations} or more donations are the backbone of the plasma community — your dedication places you among the most impactful.",
                        ["lifetime_donations"], ["champion"], ["0-2wk","3-5wk"], 1018),
    "sp_reg":       blk("social_proof_regular_consistency_v1", "social_proof",
                        "Your consistency sets an example — regular donors like you are exactly who patients count on to maintain a steady supply.",
                        [], ["regular"], ["0-2wk","3-5wk","6-10wk"], 1019),
    "sp_lapsed":    blk("social_proof_lapsed_return_v1", "social_proof",
                        "Many donors who take a break choose to return — and every donation, whenever it happens, is a meaningful contribution to someone in need.",
                        [], ["at_risk","lapsed"], ["6-10wk","11-20wk","20wk+"], 1020),

    "cta_sched":    blk("cta_schedule_appointment_v1", "cta",
                        "Book your next appointment at {center_name} when you’re ready.",
                        ["center_name"], ["new","regular","champion"], ["0-2wk","3-5wk","6-10wk"], 1021),
    "cta_new":      blk("cta_new_first_visit_v1", "cta",
                        "Schedule your next donation visit at {center_name} at your convenience — our team looks forward to seeing you.",
                        ["center_name"], ["new"], ["0-2wk","3-5wk"], 1022),
    "cta_champ":    blk("cta_champion_streak_v1", "cta",
                        "Your next visit to {center_name} will keep your remarkable giving streak going — book whenever works best for you.",
                        ["center_name"], ["champion"], ["0-2wk","3-5wk"], 1023),
    "cta_gentle":   blk("cta_atrisk_gentle_v1", "cta",
                        "If the time feels right, we’d love to see you back at {center_name} — there’s no pressure, just a warm welcome waiting.",
                        ["center_name"], ["at_risk","lapsed"], ["6-10wk","11-20wk","20wk+"], 1024),
    "cta_reg":      blk("cta_regular_reminder_v1", "cta",
                        "When you’re ready to donate again, your {center_name} team will be there to welcome you back with appreciation.",
                        ["center_name"], ["regular"], ["3-5wk","6-10wk","11-20wk"], 1025),

    "sign_warm":    blk("signoff_warm_v1", "signoff",
                        "With gratitude, The BioLife team",
                        [], ALL_LC, ALL_RT, 1026),
    "sign_new":     blk("signoff_new_v1", "signoff",
                        "We’re glad you’re with us, The BioLife team",
                        [], ["new"], ["0-2wk","3-5wk"], 1027),
    "sign_champ":   blk("signoff_champion_v1", "signoff",
                        "With deep appreciation for your dedication, The BioLife team",
                        [], ["champion"], ["0-2wk","3-5wk"], 1028),
    "sign_risk":    blk("signoff_atrisk_v1", "signoff",
                        "Wishing you well, The BioLife team at {center_name}",
                        ["center_name"], ["at_risk"], ["6-10wk","11-20wk"], 1029),
    "sign_lapsed":  blk("signoff_lapsed_v1", "signoff",
                        "Warmly, The BioLife team at {center_name}",
                        ["center_name"], ["lapsed"], ["11-20wk","20wk+"], 1030),
}


def sub(text, d):
    """Token substitution."""
    return (text
            .replace("{first_name}", d["first_name"])
            .replace("{weeks_since_last_donation}", str(d["weeks_since_last_donation"]))
            .replace("{lifetime_donations}", str(d["lifetime_donations"]))
            .replace("{estimated_patients_helped}", str(d["estimated_patients_helped"]))
            .replace("{center_name}", d["center_name"]))


def donor(i, first_name, center, w, ld, ph, lc, rt):
    return {
        "donor_id": f"00000000-0000-0000-0000-{i:012d}",
        "donor_hash": f"{i:064x}",
        "first_name": first_name,
        "email": f"donor{i:03d}@example.com",
        "center_name": center,
        "weeks_since_last_donation": w,
        "lifetime_donations": ld,
        "estimated_patients_helped": ph,
        "lifecycle_stage": lc,
        "recency_tier": rt,
        "deferral_status": "eligible",
        "deferral_until": None,
        "consent_email": True,
        "created_at": DONOR_TS,
    }


def assemble_email(d, subj_key, open_key, imp_key, sp_key, cta_key, sign_key,
                   extra_body=None, override_opener=None, override_impact=None):
    """Build email dict from block keys. override_* replaces body section with literal text."""
    subj_text = sub(BLOCKS[subj_key]["approved_text"], d)
    open_text = override_opener if override_opener else sub(BLOCKS[open_key]["approved_text"], d)
    imp_text  = override_impact if override_impact else sub(BLOCKS[imp_key]["approved_text"], d)
    sp_text   = sub(BLOCKS[sp_key]["approved_text"], d)
    cta_text  = sub(BLOCKS[cta_key]["approved_text"], d)
    sign_text = sub(BLOCKS[sign_key]["approved_text"], d)

    parts = [open_text, imp_text, sp_text, cta_text, sign_text]
    if extra_body:
        parts.append(extra_body)
    body = "\n\n".join(parts)

    tokens = list({t for k in [open_key, imp_key, sp_key, cta_key, sign_key, subj_key]
                   for t in BLOCKS[k]["safe_tokens"]})
    return {"subject": subj_text, "body": body, "tokens_used": tokens}


def sel_blocks(subj_key, open_key, imp_key, sp_key, cta_key, sign_key):
    return {
        "subject":      BLOCKS[subj_key],
        "opener":       BLOCKS[open_key],
        "impact":       BLOCKS[imp_key],
        "social_proof": BLOCKS[sp_key],
        "cta":          BLOCKS[cta_key],
        "signoff":      BLOCKS[sign_key],
    }


def ex(eid, notes, d, email, blocks, verdict, failures=None):
    return {
        "example_id": eid,
        "notes": notes,
        "donor": d,
        "email": email,
        "selected_blocks": blocks,
        "expected_verdict": verdict,
        "expected_failures": failures or [],
    }


# ---------------------------------------------------------------------------
# 30 SHOULD-PASS examples
# ---------------------------------------------------------------------------

def should_pass():
    examples = []

    # --- NEW (gold_001 – gold_006) ---
    new_combos = [
        (1,  "Priya",  "BioLife Mumbai",    1, 2, 1, "0-2wk"),
        (2,  "Arjun",  "BioLife Delhi",     4, 3, 1, "3-5wk"),
        (3,  "Sunita", "BioLife Pune",      2, 1, 1, "0-2wk"),
        (4,  "Rohan",  "BioLife Bengaluru", 3, 4, 2, "3-5wk"),
        (5,  "Meena",  "BioLife Hyderabad", 1, 2, 1, "0-2wk"),
        (6,  "Vikram", "BioLife Mumbai",    5, 5, 2, "3-5wk"),
    ]
    for i, fn, cn, w, ld, ph, rt in new_combos:
        d = donor(i, fn, cn, w, ld, ph, "new", rt)
        imp_key = "imp_personal" if ph > 1 else "imp_new"
        email = assemble_email(d, "subj_new", "open_new", imp_key, "sp_new", "cta_new", "sign_new")
        blocks = sel_blocks("subj_new", "open_new", imp_key, "sp_new", "cta_new", "sign_new")
        examples.append(ex(f"gold_{i:03d}",
                           f"New donor, {rt} recency — warm welcome, all dimensions pass",
                           d, email, blocks, "pass"))

    # --- REGULAR (gold_007 – gold_012) ---
    reg_combos = [
        (7,  "Ananya", "BioLife Bengaluru", 2, 18,  9, "0-2wk", "cta_sched"),
        (8,  "Karan",  "BioLife Pune",      4, 25, 12, "3-5wk", "cta_sched"),
        (9,  "Deepa",  "BioLife Mumbai",    6, 12,  6, "6-10wk","cta_reg"),
        (10, "Suresh", "BioLife Delhi",     3, 20, 10, "3-5wk", "cta_sched"),
        (11, "Nalini", "BioLife Hyderabad", 2, 15,  7, "0-2wk", "cta_sched"),
        (12, "Rajesh", "BioLife Bengaluru", 7, 30, 15, "6-10wk","cta_reg"),
    ]
    for i, fn, cn, w, ld, ph, rt, cta_key in reg_combos:
        d = donor(i, fn, cn, w, ld, ph, "regular", rt)
        email = assemble_email(d, "subj_reg", "open_reg", "imp_personal", "sp_reg", cta_key, "sign_warm")
        blocks = sel_blocks("subj_reg", "open_reg", "imp_personal", "sp_reg", cta_key, "sign_warm")
        examples.append(ex(f"gold_{i:03d}",
                           f"Regular donor, {rt} recency — appreciation tone, all dimensions pass",
                           d, email, blocks, "pass"))

    # --- CHAMPION (gold_013 – gold_018) ---
    champ_combos = [
        (13, "Lakshmi", "BioLife Delhi",    1, 75,  37, "0-2wk"),
        (14, "Sanjay",  "BioLife Mumbai",   3, 90,  45, "3-5wk"),
        (15, "Anika",   "BioLife Bengaluru",2, 60,  30, "0-2wk"),
        (16, "Ravi",    "BioLife Pune",     4, 100, 50, "3-5wk"),
        (17, "Uma",     "BioLife Hyderabad",1, 80,  40, "0-2wk"),
        (18, "Manoj",   "BioLife Delhi",    5, 55,  27, "3-5wk"),
    ]
    for i, fn, cn, w, ld, ph, rt in champ_combos:
        d = donor(i, fn, cn, w, ld, ph, "champion", rt)
        email = assemble_email(d, "subj_champ", "open_champ", "imp_champ", "sp_champ", "cta_champ", "sign_champ")
        blocks = sel_blocks("subj_champ", "open_champ", "imp_champ", "sp_champ", "cta_champ", "sign_champ")
        examples.append(ex(f"gold_{i:03d}",
                           f"Champion donor, {rt} — milestone recognition, all dimensions pass",
                           d, email, blocks, "pass"))

    # --- AT_RISK (gold_019 – gold_024) ---
    risk_combos = [
        (19, "Preethi", "BioLife Mumbai",    7,  8, 4, "6-10wk"),
        (20, "Vivek",   "BioLife Delhi",    12, 15, 7, "11-20wk"),
        (21, "Kavitha", "BioLife Bengaluru", 9, 12, 6, "6-10wk"),
        (22, "Arun",    "BioLife Pune",     15, 20,10, "11-20wk"),
        (23, "Nandini", "BioLife Hyderabad", 8, 10, 5, "6-10wk"),
        (24, "Gopal",   "BioLife Mumbai",   11, 18, 9, "11-20wk"),
    ]
    for i, fn, cn, w, ld, ph, rt in risk_combos:
        d = donor(i, fn, cn, w, ld, ph, "at_risk", rt)
        email = assemble_email(d, "subj_risk", "open_risk", "imp_risk", "sp_lapsed", "cta_gentle", "sign_risk")
        blocks = sel_blocks("subj_risk", "open_risk", "imp_risk", "sp_lapsed", "cta_gentle", "sign_risk")
        examples.append(ex(f"gold_{i:03d}",
                           f"At-risk donor, {rt} — gentle reconnect, all dimensions pass",
                           d, email, blocks, "pass"))

    # --- LAPSED (gold_025 – gold_030) ---
    lapsed_combos = [
        (25, "Shreya",  "BioLife Delhi",    22,  5, 2, "20wk+"),
        (26, "Nikhil",  "BioLife Bengaluru",28,  8, 4, "20wk+"),
        (27, "Padma",   "BioLife Hyderabad",18,  3, 1, "11-20wk"),
        (28, "Aditya",  "BioLife Mumbai",   35, 12, 6, "20wk+"),
        (29, "Bhavani", "BioLife Pune",     16,  7, 3, "11-20wk"),
        (30, "Chetan",  "BioLife Delhi",    25, 10, 5, "20wk+"),
    ]
    for i, fn, cn, w, ld, ph, rt in lapsed_combos:
        d = donor(i, fn, cn, w, ld, ph, "lapsed", rt)
        email = assemble_email(d, "subj_risk", "open_lapsed", "imp_lapsed", "sp_lapsed", "cta_gentle", "sign_lapsed")
        blocks = sel_blocks("subj_risk", "open_lapsed", "imp_lapsed", "sp_lapsed", "cta_gentle", "sign_lapsed")
        examples.append(ex(f"gold_{i:03d}",
                           f"Lapsed donor, {rt} — warm welcome-back, all dimensions pass",
                           d, email, blocks, "pass"))

    return examples


# ---------------------------------------------------------------------------
# 20 SHOULD-FAIL examples
# ---------------------------------------------------------------------------

def should_fail():
    examples = []

    # --- Faithfulness + donor_fact_correctness failures (gold_031–033) ---
    # Extra sentence with a number NOT in donor's allowed set

    d31 = donor(31, "Karan-F", "BioLife Pune", 2, 18, 9, "regular", "0-2wk")
    email31 = assemble_email(d31, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
        extra_body="Over your 50 dedicated visits, you have become an inspiration to the entire BioLife Pune community.")
    examples.append(ex("gold_031",
        "Faithfulness fail: email claims 50 donations but donor has 18",
        d31, email31,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["faithfulness","donor_fact_correctness"]))

    d32 = donor(32, "Deepa-F", "BioLife Mumbai", 3, 12, 6, "regular", "3-5wk")
    email32 = assemble_email(d32, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
        extra_body="Your cumulative impact has helped approximately 100 patients across India receive vital treatment.")
    examples.append(ex("gold_032",
        "Faithfulness fail: email claims 100 patients but donor helped 6",
        d32, email32,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["faithfulness","donor_fact_correctness"]))

    d33 = donor(33, "Suresh-F", "BioLife Delhi", 6, 20, 10, "regular", "6-10wk")
    email33 = assemble_email(d33, "subj_reg","open_reg","imp_personal","sp_reg","cta_reg","sign_warm",
        extra_body="It has been about 30 days since your last donation — which is just about the right time to visit again.")
    examples.append(ex("gold_033",
        "Faithfulness fail: email claims 30 days since donation but donor profile shows 6 weeks",
        d33, email33,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_reg","sign_warm"),
        "fail", ["faithfulness","donor_fact_correctness"]))

    # --- Claim accuracy failures (gold_034–036) ---

    d34 = donor(34, "Ananya-C", "BioLife Bengaluru", 2, 18, 9, "regular", "0-2wk")
    email34 = assemble_email(d34, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
        extra_body="BioLife plasma contributes to the manufacturing of Hizentra for patients in need.")
    examples.append(ex("gold_034",
        "Claim accuracy fail: email names prohibited therapy Hizentra",
        d34, email34,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["claim_accuracy"]))

    d35 = donor(35, "Nalini-C", "BioLife Hyderabad", 2, 15, 7, "regular", "0-2wk")
    email35 = assemble_email(d35, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
        extra_body="Your plasma donation helps cure rare conditions affecting thousands of patients worldwide.")
    examples.append(ex("gold_035",
        "Claim accuracy fail: email uses prohibited word 'cure' for a medical outcome",
        d35, email35,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["claim_accuracy"]))

    d36 = donor(36, "Rajesh-C", "BioLife Bengaluru", 7, 30, 15, "regular", "6-10wk")
    email36 = assemble_email(d36, "subj_reg","open_reg","imp_personal","sp_reg","cta_reg","sign_warm",
        extra_body="Plasma donations like yours are used to treat primary immunodeficiency and other rare blood conditions.")
    examples.append(ex("gold_036",
        "Claim accuracy fail: email states plasma 'treats' a specific named medical condition",
        d36, email36,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_reg","sign_warm"),
        "fail", ["claim_accuracy"]))

    # --- Brand voice failures (gold_037–039) ---

    d37 = donor(37, "Ritu", "BioLife Mumbai", 1, 18, 9, "regular", "0-2wk")
    email37 = assemble_email(d37, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
        extra_body="Act now — schedule your donation this week before spots fill up!")
    examples.append(ex("gold_037",
        "Brand voice fail: urgency language 'Act now' violates warm professional tone",
        d37, email37,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["brand_voice"]))

    d38 = donor(38, "Arjun-B", "BioLife Pune", 4, 25, 12, "regular", "3-5wk")
    email38 = assemble_email(d38, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
        extra_body="Don't miss this amazing opportunity to be part of something incredible this month!")
    examples.append(ex("gold_038",
        "Brand voice fail: superlatives 'amazing' and 'incredible' violate brand voice",
        d38, email38,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["brand_voice"]))

    d39 = donor(39, "Meena-B", "BioLife Hyderabad", 2, 15, 7, "regular", "0-2wk")
    email39 = assemble_email(d39, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
        extra_body="Hurry! Book your appointment today — patients are counting on you to sign up right away.")
    examples.append(ex("gold_039",
        "Brand voice fail: 'Hurry!' creates pressure and urgency not appropriate for BioLife tone",
        d39, email39,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["brand_voice"]))

    # --- Toxicity / sensitivity failures (gold_040–042) ---

    d40 = donor(40, "Parvati", "BioLife Mumbai", 24, 6, 3, "lapsed", "20wk+")
    email40 = assemble_email(d40, "subj_risk","open_lapsed","imp_lapsed","sp_lapsed","cta_gentle","sign_lapsed",
        extra_body="We hope you understand that patients who rely on plasma therapy are affected when their regular donors take extended breaks.")
    examples.append(ex("gold_040",
        "Toxicity fail: links donor absence to patient harm — implicit guilt-tripping",
        d40, email40,
        sel_blocks("subj_risk","open_lapsed","imp_lapsed","sp_lapsed","cta_gentle","sign_lapsed"),
        "fail", ["toxicity_sensitivity"]))

    d41 = donor(41, "Ramesh", "BioLife Delhi", 18, 9, 4, "lapsed", "11-20wk")
    email41 = assemble_email(d41, "subj_risk","open_lapsed","imp_lapsed","sp_lapsed","cta_gentle","sign_lapsed",
        extra_body="Your absence has been felt by the patients who depend on a consistent plasma supply throughout the year.")
    examples.append(ex("gold_041",
        "Toxicity fail: 'your absence has been felt by patients' — direct guilt-tripping",
        d41, email41,
        sel_blocks("subj_risk","open_lapsed","imp_lapsed","sp_lapsed","cta_gentle","sign_lapsed"),
        "fail", ["toxicity_sensitivity"]))

    d42 = donor(42, "Sita", "BioLife Pune", 8, 12, 6, "at_risk", "6-10wk")
    email42 = assemble_email(d42, "subj_risk","open_risk","imp_risk","sp_lapsed","cta_gentle","sign_risk",
        extra_body="The declining donor count in your area means patients may not receive the plasma they urgently need.")
    examples.append(ex("gold_042",
        "Toxicity fail: implies patient harm from donor shortage, creating emotional pressure on at-risk donor",
        d42, email42,
        sel_blocks("subj_risk","open_risk","imp_risk","sp_lapsed","cta_gentle","sign_risk"),
        "fail", ["toxicity_sensitivity"]))

    # --- Segment fit failures (gold_043–045) ---

    # New donor receives lapsed-reconnection email
    d43 = donor(43, "Seema", "BioLife Mumbai", 1, 2, 1, "new", "0-2wk")
    email43 = assemble_email(d43, "subj_risk","open_lapsed","imp_lapsed","sp_lapsed","cta_gentle","sign_lapsed")
    examples.append(ex("gold_043",
        "Segment fit fail: new donor (just joined) receives 'we miss you' lapsed reconnection messaging",
        d43, email43,
        sel_blocks("subj_risk","open_lapsed","imp_lapsed","sp_lapsed","cta_gentle","sign_lapsed"),
        "fail", ["segment_fit","faithfulness"]))

    # Champion donor receives new-donor welcome email
    d44 = donor(44, "Sanjay-S", "BioLife Mumbai", 1, 90, 45, "champion", "0-2wk")
    email44 = assemble_email(d44, "subj_new","open_new","imp_new","sp_new","cta_new","sign_new")
    examples.append(ex("gold_044",
        "Segment fit fail: champion donor with 90 donations receives new-donor 'welcome to the family' email",
        d44, email44,
        sel_blocks("subj_new","open_new","imp_new","sp_new","cta_new","sign_new"),
        "fail", ["segment_fit","faithfulness"]))

    # Regular donor receives at-risk reconnect email
    d45 = donor(45, "Kiran", "BioLife Pune", 8, 22, 11, "regular", "6-10wk")
    email45 = assemble_email(d45, "subj_risk","open_risk","imp_risk","sp_lapsed","cta_gentle","sign_risk")
    examples.append(ex("gold_045",
        "Segment fit fail: regular active donor receives at-risk 'we noticed your gap' messaging",
        d45, email45,
        sel_blocks("subj_risk","open_risk","imp_risk","sp_lapsed","cta_gentle","sign_risk"),
        "fail", ["segment_fit"]))

    # --- Block attribution failures (gold_046–047) ---

    d46 = donor(46, "Priya-BA", "BioLife Bengaluru", 2, 18, 9, "regular", "0-2wk")
    # Opener is paraphrased in the email body
    paraphrased_opener46 = f"Hi Priya-BA, your dedicated plasma donations continue to inspire us at BioLife Bengaluru."
    email46 = assemble_email(d46, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
                             override_opener=paraphrased_opener46)
    examples.append(ex("gold_046",
        "Block attribution fail: opener block paraphrased — 'dedicated plasma donations' instead of 'ongoing commitment to plasma donation'",
        d46, email46,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["block_attribution"]))

    d47 = donor(47, "Ananya-BA", "BioLife Bengaluru", 2, 18, 9, "regular", "0-2wk")
    # Impact is paraphrased in the email body
    paraphrased_impact47 = "Your donations have contributed to approximately 9 people getting the help they need."
    email47 = assemble_email(d47, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
                             override_impact=paraphrased_impact47)
    examples.append(ex("gold_047",
        "Block attribution fail: impact block paraphrased — 'approximately 9 people' instead of 'estimated 9 patients receive life-saving therapies'",
        d47, email47,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["block_attribution"]))

    # --- Length / readability failure (gold_048) ---

    d48 = donor(48, "Suresh-LR", "BioLife Delhi", 2, 20, 10, "regular", "0-2wk")
    dense = (
        "The biospecimen collection, fractionation, and reconstitution methodologies employed in "
        "immunoglobulin manufacturing necessitate rigorous quality control protocols encompassing "
        "immunochemical characterization, spectrophotometric quantification, electrophoretic "
        "verification, chromatographic purification, pathogen inactivation procedures, sterility "
        "testing, and final formulation analytics before pharmaceutical-grade immunoglobulin "
        "concentrates can be administered therapeutically to immunocompromised recipients "
        "requiring ongoing immunological supplementation."
    )
    email48 = assemble_email(d48, "subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm",
        extra_body=dense)
    examples.append(ex("gold_048",
        "Length/readability fail: dense pharmaceutical jargon appended to body drives Flesch score below 60",
        d48, email48,
        sel_blocks("subj_reg","open_reg","imp_personal","sp_reg","cta_sched","sign_warm"),
        "fail", ["length_readability"]))

    # --- Donor fact correctness failures (gold_049–050) ---

    d49 = donor(49, "Gopal-DF", "BioLife Mumbai", 11, 8, 3, "at_risk", "11-20wk")
    # Extra sentence with 10, which is NOT in {11, 8, 3}
    email49 = assemble_email(d49, "subj_risk","open_risk","imp_risk","sp_lapsed","cta_gentle","sign_risk",
        extra_body="Your generous spirit has helped approximately 10 patients through your dedication.")
    examples.append(ex("gold_049",
        "Donor fact correctness fail: email claims 10 patients but donor profile shows estimated_patients_helped=3",
        d49, email49,
        sel_blocks("subj_risk","open_risk","imp_risk","sp_lapsed","cta_gentle","sign_risk"),
        "fail", ["donor_fact_correctness","faithfulness"]))

    d50 = donor(50, "Vivek-DF", "BioLife Delhi", 9, 7, 3, "at_risk", "6-10wk")
    # Extra sentence with 15, which is NOT in {9, 7, 3}
    email50 = assemble_email(d50, "subj_risk","open_risk","imp_risk","sp_lapsed","cta_gentle","sign_risk",
        extra_body="You've made 15 visits to our center and each one has made a difference.")
    examples.append(ex("gold_050",
        "Donor fact correctness fail: email claims 15 visits but donor profile shows lifetime_donations=7",
        d50, email50,
        sel_blocks("subj_risk","open_risk","imp_risk","sp_lapsed","cta_gentle","sign_risk"),
        "fail", ["donor_fact_correctness","faithfulness"]))

    return examples


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    examples = should_pass() + should_fail()
    assert len(examples) == 50, f"Expected 50 examples, got {len(examples)}"

    pass_count = sum(1 for e in examples if e["expected_verdict"] == "pass")
    fail_count = sum(1 for e in examples if e["expected_verdict"] == "fail")
    print(f"Generated {len(examples)} examples: {pass_count} pass, {fail_count} fail")

    OUT.write_text(json.dumps(examples, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written to {OUT}")

    # Quick sanity: verify no should-pass example has unintended numbers
    import re
    comma_re = re.compile(r"(\d),(\d)")
    for e in examples:
        if e["expected_verdict"] != "pass":
            continue
        d = e["donor"]
        allowed = {d["weeks_since_last_donation"], d["lifetime_donations"], d["estimated_patients_helped"]}
        text = e["email"]["subject"] + " " + e["email"]["body"]
        text = comma_re.sub(r"\1\2", text)
        ints = [int(m) for m in re.findall(r"\b\d+\b", text)]
        bad = [n for n in ints if n not in allowed]
        if bad:
            print(f"  WARNING: {e['example_id']} ({d['first_name']}) has unexpected integers: {bad}")
    print("Sanity check done.")


if __name__ == "__main__":
    main()
