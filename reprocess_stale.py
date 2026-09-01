import sys
from idos.decision.assessment_pipeline import run_full_pipeline

stale_oppids = [
    ('OPP-20260725-012', 'ADBE'),
    ('OPP-20260725-019', 'ANF'),
    ('OPP-20260725-021', 'BKNG'),
    ('OPP-20260725-023', 'CCL'),
    ('OPP-20260725-017', 'CDE'),
    ('OPP-20260725-009', 'DECK'),
    ('OPP-20260725-026', 'HL'),
    ('OPP-20260725-022', 'LVS'),
    ('OPP-20260725-010', 'NEM'),
    ('OPP-20260725-001', 'PAAS'),
    ('OPP-20260725-013', 'SAP'),
    ('OPP-20260725-014', 'SBS'),
    ('OPP-20260725-027', 'SCCO'),
    ('OPP-20260725-029', 'SPGI'),
    ('OPP-20260725-007', 'AEM'),
    ('OPP-20260730-001', 'AMZN'),
    ('OPP-20260725-006', 'FSLR'),
    ('OPP-20260725-004', 'KGC'),
]

for opp_id, ticker in stale_oppids:
    r = run_full_pipeline(opp_id, ticker, '.', force_reprocess=True)
    print(f"{ticker} {opp_id}: board_approved={r['board_approved']}, rules_failed={r['rules_failed']}, status={r['status']}")
