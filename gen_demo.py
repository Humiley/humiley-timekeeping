"""Generate a self-contained demo dataset (Jan 2024 -> today) for the standalone
training HTML. Reuses the rich HR data already in the repo DB and generates the
PMC projects, CRM pipeline, leave history and monthly payroll on top."""
import sys, json, datetime, random
sys.path.insert(0, '.')
import db

random.seed(42)
TODAY = datetime.date(2026, 6, 24)
conn = db.get_conn()
def rows(t):
    cur = conn.execute("SELECT * FROM " + t)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

employees = rows('employees')
attendance = rows('attendance')
zones = rows('zones')
coll = {}
for r in conn.execute("SELECT coll, id, data FROM collections").fetchall():
    coll.setdefault(r[0], []).append(json.loads(r[2]))
conn.close()

emp_names = [e['name'] for e in employees if e.get('name')]
mgrs = [e['name'] for e in employees if e.get('role') == 'manager'] or emp_names[:3]
def pick(seq, i): return seq[i % len(seq)]
_id = {}
def nid(p):
    _id[p] = _id.get(p, 0) + 1
    return p + '-' + str(_id[p]).zfill(4)

# ---------------- LEAVE history 2024 -> now ----------------
leave = []
ltypes = ['Annual', 'Sick', 'Unpaid', 'Marriage', 'Bereavement']
for i in range(46):
    e = pick(employees, i * 7)
    yr = 2024 + (i % 3)
    mo = (i % 12) + 1
    d1 = datetime.date(yr, mo, min(1 + (i % 25), 28))
    dur = 1 + (i % 4)
    d2 = d1 + datetime.timedelta(days=dur - 1)
    if d1 > TODAY: continue
    st = 'Approved' if d2 < TODAY else random.choice(['Pending', 'Approved'])
    leave.append({'id': nid('lv'), 'emp_id': e['id'], 'empId': e['id'], 'name': e.get('name'),
                  'type': pick(ltypes, i), 'start': d1.isoformat(), 'end': d2.isoformat(),
                  'days': dur, 'reason': pick(['Family trip', 'Medical', 'Personal', 'Rest', 'Wedding'], i),
                  'status': st, 'approver': pick(mgrs, i)})

# ---------------- PAYRUNS monthly 2024 -> now ----------------
payruns = []
d = datetime.date(2024, 1, 1)
while d <= TODAY:
    base = 1_500_000_000 + (d.year - 2024) * 120_000_000 + d.month * 3_000_000
    gross = base; pit = int(gross * 0.09); ee = int(gross * 0.105); er = int(gross * 0.215)
    net = gross - pit - ee
    payruns.append({'id': nid('pay'), 'scope': 'company', 'period': '%04d-%02d' % (d.year, d.month),
                    'count': len(employees), 'gross': gross, 'net': net, 'ee': ee, 'er': er, 'pit': pit,
                    'erCost': gross + er, 'status': 'Finalised',
                    'created': db_fmt(d) if False else d.strftime('%b-%d-%y')})
    d = datetime.date(d.year + (d.month // 12), (d.month % 12) + 1, 1)

# ---------------- CRM ----------------
companies = []
crm_co = [('Azure Hospitality', 'Hospitality', 'Da Nang'), ('Bao Minh Pharma', 'Pharmaceutical', 'Binh Duong'),
          ('Metro Rail Authority', 'Government', 'HCMC'), ('Sunrise Industrial JSC', 'Manufacturing', 'Long An'),
          ('RedDragon Logistics', 'Logistics', 'Hai Phong'), ('GreenField Developments', 'Real Estate', 'Hanoi'),
          ('VietBank', 'Finance', 'HCMC'), ('Mega LifeSciences', 'Pharmaceutical', 'Binh Duong')]
for i, (nm, ind, loc) in enumerate(crm_co):
    companies.append({'id': nid('crm_co'), 'name': nm, 'industry': ind, 'location': loc,
                      'owner': pick(mgrs, i), 'website': 'www.' + nm.split()[0].lower() + '.com',
                      'status': 'Active', 'tier': pick(['Key', 'Standard', 'Prospect'], i)})
contacts = []
for i in range(14):
    co = pick(crm_co, i)[0]
    contacts.append({'id': nid('crm_ct'), 'name': pick(['Mr. Tuan', 'Ms. Lan', 'Mr. Khoa', 'Ms. Mai', 'Mr. Phong', 'Ms. Yen', 'Mr. Long'], i) + ' ' + chr(65 + i),
                     'company': co, 'title': pick(['Director', 'PM', 'Procurement Lead', 'CEO', 'Engineer'], i),
                     'email': 'contact%d@%s.com' % (i, co.split()[0].lower()), 'phone': '09%08d' % (i * 1234567 % 100000000),
                     'owner': pick(mgrs, i)})
products = [{'id': nid('crm_pr'), 'name': n, 'category': c, 'price': p, 'unit': 'project'} for n, c, p in
            [('PMC Services', 'Service', 0), ('Design Management', 'Service', 0), ('Cost Management', 'Service', 0),
             ('Commissioning & Qualification', 'Service', 0), ('Construction Supervision', 'Service', 0), ('Owner Engineer', 'Service', 0)]]
deals = []
stages = ['Lead', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost']
for i in range(16):
    yr = 2024 + (i % 3); co = pick(crm_co, i)[0]
    val = (2 + i % 9) * 1_000_000_000
    st = pick(stages, i)
    deals.append({'id': nid('crm_dl'), 'title': pick(['EPC PMC', 'Design Mgmt', 'Cost & Contract', 'Supervision', 'C&Q'], i) + ' — ' + co.split()[0],
                  'company': co, 'value': val, 'stage': st, 'owner': pick(mgrs, i),
                  'probability': {'Lead': 10, 'Qualified': 30, 'Proposal': 50, 'Negotiation': 70, 'Won': 100, 'Lost': 0}[st],
                  'closeDate': datetime.date(yr, (i % 12) + 1, 15).isoformat(),
                  'product': pick([p['name'] for p in products], i)})

# ---------------- PMC PROJECTS (5) + sub-records, spanning 2024 -> 2026 ----------------
import re as _re
def p3(nm): return (_re.sub(r'[^A-Za-z0-9]', '', nm or '')[:3] or 'PRJ').upper()
PM_PEOPLE = ['Dung Nguyen', 'Son Nguyen', 'Trung Nguyen', 'Duc Nguyen', 'Vu Nguyen', 'Yen Pham', 'Tony Nguyen']
POOLS = {'PMC-2025-031': ['Truong Son Construction', 'NTC', 'REE M&E', 'Decor Asia'],
         'PMC-2026-014': ['Hoa Binh Corp', 'Coteccons', 'TVE'], 'PMC-2026-009': ['CC1', 'REE M&E', 'NTC'],
         'ENG-2026-021': ['Humiley ENG', 'Apave'], 'PMC-2025-018': ['Humiley', 'Fico']}
ITP_BY = {'PMC-2025-031': [('Structural ITP', 'Structural', 'ACI 318', 'Approved'), ('Pool & waterproofing ITP', 'Civil', 'Manufacturer spec', 'Approved'), ('MEP & FF&E ITP', 'MEP', 'Project spec', 'Draft')],
          'PMC-2026-014': [('Piling ITP', 'Geotechnical', 'TCVN 9393:2012', 'Approved'), ('Concrete works ITP', 'Structural', 'ACI 318', 'Approved')],
          'PMC-2026-009': [('Finishes ITP', 'Architectural', 'Project spec', 'Approved'), ('MEP installation ITP', 'MEP', 'BS EN', 'Draft')],
          'ENG-2026-021': [('Design QA ITP', 'QA/QC', 'ISO 9001', 'Approved')],
          'PMC-2025-018': [('Infrastructure ITP', 'Civil', 'TCVN', 'Approved')]}
PROJECTS = [
  dict(code='PMC-2025-031', name='Coastal Resort — EPC Project Management', account='Azure Hospitality', location='Da Nang', dept='PMC', status='Executing', phase='Construction / Execution', start='2024-09-01', end='2026-10-30', budget=18_000_000_000, contract=21_000_000_000, mgr='Dung Nguyen', sponsor='Mr. Tuan (Owner Rep)', pct=62, obj='Manage EPC delivery of a 120-key beachfront resort to opening date and budget.'),
  dict(code='PMC-2026-014', name='Riverside Tower — Construction Supervision', account='GreenField Developments', location='Hanoi', dept='PMC', status='Executing', phase='Construction / Execution', start='2024-03-01', end='2026-12-15', budget=9_500_000_000, contract=11_000_000_000, mgr='Son Nguyen', sponsor='Ms. Lan', pct=48, obj='Independent construction supervision of a 28-floor mixed-use tower.'),
  dict(code='PMC-2026-009', name='Metro Line 3 — Station Fit-out PMC', account='Metro Rail Authority', location='HCMC', dept='PMC', status='Executing', phase='Construction / Execution', start='2024-06-01', end='2026-08-30', budget=14_000_000_000, contract=15_500_000_000, mgr='Trung Nguyen', sponsor='MRA Board', pct=55, obj='PMC for architectural & MEP fit-out of 4 underground stations to CRA standards.'),
  dict(code='ENG-2026-021', name='Bao Minh Factory Expansion — Design Management', account='Bao Minh Pharma', location='Binh Duong', dept='Engineering', status='Planning', phase='Design', start='2025-11-01', end='2026-10-15', budget=4_200_000_000, contract=5_000_000_000, mgr='Duc Nguyen', sponsor='Bao Minh COO', pct=22, obj='Design management for a GMP pharma factory expansion (DQ/IQ/OQ ready).'),
  dict(code='PMC-2025-018', name='Sunrise Industrial Park Ph.2 — Cost & Contract Mgmt', account='Sunrise Industrial JSC', location='Long An', dept='PMC', status='Closing', phase='Closeout', start='2024-01-15', end='2026-06-30', budget=12_000_000_000, contract=12_800_000_000, mgr='Tony Nguyen', sponsor='Sunrise Board', pct=94, obj='Cost & contract management for Phase-2 industrial park infrastructure.'),
]
P = {k: [] for k in ['pm_projects', 'pm_deliverables', 'pm_tasks', 'pm_costs', 'pm_risks', 'pm_quality', 'pm_quality_itp', 'pm_resources', 'pm_comms', 'pm_issues', 'pm_stakeholders', 'pm_rfis', 'pm_sitereports', 'pm_changes', 'pm_lessons', 'pm_procurement', 'pm_procurement_payments']}
def band(sc): return 'Low' if sc <= 4 else 'Medium' if sc <= 9 else 'High' if sc <= 14 else 'Critical'
def quad(inf, intr):
    hiP = inf in ('High', 'Medium'); hiI = intr in ('High', 'Medium')
    return 'Manage Closely' if hiP and hiI else 'Keep Satisfied' if hiP else 'Keep Informed' if hiI else 'Monitor'
WBS = [('1.0', 'Design basis & surveys'), ('2.0', 'Concept design'), ('3.0', 'Detailed design (multi-discipline)'), ('4.0', 'Procurement & tender'), ('5.0', 'Construction / installation'), ('6.0', 'Commissioning & handover')]
for pr in PROJECTS:
    code = pr['code']; pid = 'pm_-' + code.replace('-', ''); pre = p3(pr['name']); pool = POOLS[code]
    sy, sm = int(pr['start'][:4]), int(pr['start'][5:7]); ey = int(pr['end'][:4])
    P['pm_projects'].append({'id': pid, 'code': code, 'name': pr['name'], 'account': pr['account'], 'client': pr['account'],
        'manager': pr['mgr'], 'dept': pr['dept'], 'location': pr['location'], 'status': pr['status'], 'phase': pr['phase'],
        'startPlanned': pr['start'], 'endPlanned': pr['end'], 'budget': pr['budget'], 'contractValue': pr['contract'],
        'sponsor': pr['sponsor'], 'contractType': 'EPC / Turnkey', 'members': ', '.join(PM_PEOPLE[:3]),
        'objectives': pr['obj'], 'scopeSummary': 'Full PMC scope: design, procurement, construction supervision, C&Q and handover.',
        'successCriteria': 'Handover on schedule; CPI/SPI ≥ 0.95; zero major NCRs at DLP.', 'pct': pr['pct'], 'percentComplete': pr['pct'],
        'ragReason': '' if pr['pct'] >= 50 else 'Early phase — watch schedule float.'})
    for i, (w, nm) in enumerate(WBS):
        mo = sm + i * 3; yy = sy + (mo - 1) // 12; mo = (mo - 1) % 12 + 1
        st = '%04d-%02d-05' % (yy, mo); fm = '%04d-%02d-20' % (yy + (mo + 1 > 12), (mo % 12) + 1)
        donep = min(100, max(0, pr['pct'] - i * 12 + 20))
        P['pm_deliverables'].append({'id': nid('pm_del'), 'projectId': pid, 'wbsCode': w, 'name': nm, 'owner': pick(pool, i),
            'supervisor': pick(PM_PEOPLE, i), 'due': fm, 'weight': [10, 15, 25, 15, 25, 10][i], 'percentComplete': donep,
            'status': 'Accepted' if donep >= 100 else 'In progress' if donep > 0 else 'Not started',
            'acceptanceCriteria': 'Per spec & code'})
        P['pm_tasks'].append({'id': nid('pm_tsk'), 'projectId': pid, 'wbs': w, 'name': nm, 'assignee': pick(PM_PEOPLE, i),
            'start': st, 'finish': fm, 'pctComplete': donep, 'status': 'Completed' if donep >= 100 else 'In progress' if donep > 0 else 'Not started',
            'isMilestone': 'No', 'critical': 'Yes' if i in (2, 4) else 'No', 'phase': pr['phase']})
    # milestones
    for j, (mn, md) in enumerate([('Design freeze', '%d-04-15' % (sy + 1)), ('Topping out', '%d-07-31' % (sy + 1)), ('Practical completion', pr['end'])]):
        P['pm_tasks'].append({'id': nid('pm_tsk'), 'projectId': pid, 'wbs': 'M%d' % (j + 1), 'name': mn, 'assignee': pr['mgr'],
            'start': md, 'finish': md, 'pctComplete': 0, 'status': 'Not started', 'isMilestone': 'Yes', 'critical': 'Yes', 'phase': pr['phase']})
    cats = [('Design fees', 'Design'), ('Civil & structure', 'Construction'), ('MEP works', 'Construction'), ('FF&E', 'Procurement'), ('PMC fee', 'Management')]
    for i, (it, cat) in enumerate(cats):
        bud = pr['budget'] // 5; act = int(bud * (pr['pct'] / 100) * (0.9 + 0.04 * i))
        P['pm_costs'].append({'id': nid('pm_cost'), 'projectId': pid, 'item': it, 'category': cat, 'budget': bud,
            'committed': int(bud * 0.95), 'actual': act, 'invoiced': int(act * 0.9), 'owner': pr['mgr'], 'status': 'Incurred'})
    risks = [('Typhoon season delays', 'External', 4, 5, 'Mitigate'), ('Cost overrun on rework', 'Cost', 4, 4, 'Mitigate'),
             ('Supply lead time', 'Schedule', 3, 4, 'Transfer'), ('Labour availability at peak', 'Resource', 3, 3, 'Mitigate')]
    for i, (t, c, pp, im, resp) in enumerate(risks, 1):
        sc = pp * im
        P['pm_risks'].append({'id': nid('pm_rsk'), 'projectId': pid, 'riskNo': '%s-RISK-%03d' % (pre, i), 'title': t, 'category': c,
            'probability': str(pp), 'impact': str(im), 'score': sc, 'exposureBand': band(sc), 'responseStrategy': resp,
            'mitigationActions': 'Owner monitoring; contingency held.', 'owner': pick(PM_PEOPLE, i), 'contractor': pick(pool, i),
            'status': 'Open' if i < 3 else 'Mitigating'})
    qy = [('NCR', 'Concrete honeycombing', 'Structural', 'Fail', 'Major', 'Open'), ('NCR', 'Waterproofing failure', 'Architectural', 'Fail', 'Critical', 'In progress'), ('Inspection', 'Pool structure', 'Civil', 'Pass', 'Minor', 'Closed')]
    for i, (ty, t, disc, res, sev, stt) in enumerate(qy, 1):
        P['pm_quality'].append({'id': nid('pm_qa'), 'projectId': pid, 'refNo': '%s-%s-%03d' % (pre, ty[:3].upper(), i), 'type': ty,
            'title': t, 'discipline': disc, 'contractor': pick(pool, i), 'raisedDate': '%d-%02d-12' % (sy + 1, (i * 2) % 6 + 1),
            'result': res, 'severity': sev, 'status': stt})
    for i, (t, disc, std, stt) in enumerate(ITP_BY[code], 1):
        sM = 3 + (i - 1) * 2
        P['pm_quality_itp'].append({'id': nid('pm_itp'), 'projectId': pid, 'itpNo': '%s-ITP-%03d' % (pre, i), 'title': t,
            'contractor': pick(pool, i), 'discipline': disc, 'standardRef': std, 'status': stt,
            'plannedStart': '%d-%02d-05' % (sy + 1, sM), 'plannedFinish': '%d-%02d-%02d' % (sy + 1, sM + 1, 15 if i % 2 else 25)})
    for i in range(5):
        P['pm_resources'].append({'id': nid('pm_res'), 'projectId': pid, 'name': pick(PM_PEOPLE, i), 'projectRole': pick(['Project Manager', 'Site Engineer', 'QA/QC Lead', 'Cost Engineer', 'MEP Lead'], i),
            'discipline': pick(['Civil', 'Structural', 'MEP', 'QA/QC', 'General / Multi'], i), 'raci': pick(['A', 'R', 'C', 'R', 'R'], i),
            'allocationPct': [100, 80, 60, 50, 70][i], 'rate': (800000 + i * 100000), 'status': 'Active'})
    for i, (ty, sub) in enumerate([('Status Report', 'Monthly Report — progress'), ('Meeting Minutes', 'Recovery workshop'), ('Notice', 'Variation notice VO-03')], 1):
        P['pm_comms'].append({'id': nid('pm_com'), 'projectId': pid, 'refNo': '%s-COM-%03d' % (pre, i), 'type': ty,
            'date': '%d-%02d-15' % (ey, (i % 6) + 1), 'subject': sub, 'audience': pick(['Owner, PMC', 'Owner, contractors', 'All'], i),
            'summary': 'See attached.', 'status': pick(['Closed', 'Open'], i)})
    for i, (t, pri, stt) in enumerate([('FF&E supplier delay 6 weeks', 'High', 'Open'), ('Typhoon damage to villa roofs', 'High', 'In progress')], 1):
        P['pm_issues'].append({'id': nid('pm_iss'), 'projectId': pid, 'issueNo': '%s-ISS-%03d' % (pre, i), 'title': t, 'category': 'Schedule',
            'priority': pri, 'owner': pick(PM_PEOPLE, i), 'status': stt, 'due': '%d-07-%02d' % (ey, 15 + i * 5)})
    sk = [('Mr. Tuan', pr['account'], 'Owner Representative', 'External', 'High', 'High', 'Resistor'),
          ('Hotel Operator', 'Azure Brand', 'Future operator', 'External', 'High', 'High', 'Neutral'),
          ('Lenders', 'VietBank', 'Project finance', 'External', 'High', 'Medium', 'Neutral'),
          ('Insurer', 'Bao Viet', 'Insurance', 'External', 'Medium', 'Low', 'Neutral')]
    for i, (n2, org, role, ie, inf, intr, att) in enumerate(sk):
        P['pm_stakeholders'].append({'id': nid('pm_stk'), 'projectId': pid, 'name': n2, 'organization': org, 'role': role,
            'internalExternal': ie, 'influence': inf, 'interest': intr, 'attitude': att, 'quadrant': quad(inf, intr)})
    for i, (ty, subj, disc, stt) in enumerate([('RFI', 'Revised roof detail post-typhoon', 'Architectural', 'Open'), ('Transmittal', 'Insurance survey photos', 'General / Multi', 'Closed'), ('Submittal', 'FF&E samples — guest rooms', 'Architectural', 'Rejected')], 1):
        P['pm_rfis'].append({'id': nid('pm_rfi'), 'projectId': pid, 'number': '%s-%s-%03d' % (pre, ty[:3].upper(), i), 'type': ty,
            'subject': subj, 'discipline': disc, 'ballInCourt': pick(['Designer', 'Owner', 'PMC'], i), 'requiredBy': '%d-%02d-20' % (ey, (i % 6) + 1),
            'status': stt, 'raisedDate': '%d-%02d-01' % (ey, (i % 6) + 1)})
    for i in range(2):
        P['pm_sitereports'].append({'id': nid('pm_sdr'), 'projectId': pid, 'reportDate': '%d-06-%02d' % (ey, 18 + i), 'area': pick(['Villas block', 'Podium', 'Basement'], i),
            'weatherAm': 'Sunny', 'weatherPm': pick(['Storm warning', 'Cloudy'], i), 'manpower': 80 + i * 6,
            'workPerformed': 'Superstructure; roof rework V11-V14.', 'delays': pick(['Storm warning — secured site', 'None'], i)})
    for i, (t, sd, cd, dec) in enumerate([('Extended scope — landscape', 18, 450_000_000, 'Approved'), ('Owner-requested FF&E upgrade', 10, 800_000_000, 'Pending')], 1):
        P['pm_changes'].append({'id': nid('pm_chg'), 'projectId': pid, 'crNo': '%s-CR-%03d' % (pre, i), 'title': t, 'type': 'Scope',
            'requestedDate': '%d-%02d-10' % (ey, (i % 6) + 1), 'schedDelta': sd, 'costDelta': cd, 'decision': dec,
            'recommendation': 'Recommend approval with contingency.'})
    for i, (t, cat) in enumerate([('Early contractor engagement paid off', 'Procurement'), ('Typhoon contingency was essential', 'Risk')], 1):
        P['pm_lessons'].append({'id': nid('pm_les'), 'projectId': pid, 'phase': pr['phase'], 'title': t, 'category': cat,
            'recommendation': 'Apply on future coastal projects.'})
    pk = [('Civil & structure package', pool[0] if pool else 'TBD', 'Subcontract', pr['budget'] // 2, 'Active', 10),
          ('MEP package', pick(pool, 1), 'Subcontract', pr['budget'] // 4, 'Active', 10), ('FF&E supply', pick(pool, 3), 'PO', pr['budget'] // 9, 'Awarded', 5)]
    for i, (t, ven, ty, val, stt, ret) in enumerate(pk, 1):
        P['pm_procurement'].append({'id': nid('pm_pkg'), 'projectId': pid, 'pkgNo': '%s-PKG-%03d' % (pre, i), 'title': t, 'vendor': ven,
            'type': ty, 'value': val, 'status': stt, 'retentionPct': ret, 'awardDate': '%d-%02d-01' % (sy + 1, (i % 6) + 1)})
    for i in range(2):
        gc = pr['budget'] // 6
        P['pm_procurement_payments'].append({'id': nid('pm_ipc'), 'projectId': pid, 'certNo': '%s-IPC-%03d' % (pre, i + 1),
            'period': '%d-%02d' % (ey, i + 4), 'grossClaimed': gc, 'retentionDeducted': int(gc * 0.1), 'netCertified': int(gc * 0.9), 'status': pick(['Paid', 'Submitted'], i)})
for k, v in P.items():
    coll[k] = v
print("PM generated: %d projects, %d tasks, %d risks, %d ITP, %d procurement" % (
    len(P['pm_projects']), len(P['pm_tasks']), len(P['pm_risks']), len(P['pm_quality_itp']), len(P['pm_procurement'])))

print("base data ready: %d emps, %d attendance, %d leave, %d payruns, %d deals" % (
    len(employees), len(attendance), len(leave), len(payruns), len(deals)))

coll['crm_deals'] = deals; coll['crm_companies'] = companies; coll['crm_contacts'] = contacts
coll['crm_products'] = products; coll['payruns'] = payruns
OUT = {'employees': employees, 'attendance': attendance, 'leave': leave, 'zones': zones, 'collections': coll}
json.dump(OUT, open('demo_data.json', 'w'), default=str)
import os
print("wrote demo_data.json  (%d KB, %d collections)" % (os.path.getsize('demo_data.json') // 1024, len(coll)))
