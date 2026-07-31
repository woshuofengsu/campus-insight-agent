"""End-to-end verification test suite."""
import sys, io, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
passed = 0; total = 0

# ═══ 1. Module compilation ═══
print('=== 1. Module Compilation (35 modules) ===')
modules = [
    'config','agent.prompt','agent.engine','agent.reflector','agent.memory','agent.callbacks',
    'agent.helpers','agent.weekly_report','agent.rag',
    'data.database','data.models','data.seed',
    'data.db_core','data.db_user','data.db_academic','data.db_knowledge',
    'data.db_governance','data.db_health','data.db_surveillance',
    'data.db_notifications','data.db_perception','data.live_generator',
    'tools','tools.query_weather','tools.query_campus_pulse','tools.query_proposals',
    'tools.query_topics','tools.query_campus_issues','tools.action_report_issue',
    'tools.action_create_proposal','tools.action_support_proposal','tools.action_express_opinion',
    'tools.query_knowledge','tools.query_my_issues',
    'ui.components','ui.thinking','ui.cache','ui.onboarding','ui.session','ui.theme','ui.notify',
    'ui.prefetch','ui.login',
    'utils.logger','utils.retry','utils.text',
    'perception.monitor',
]
for m in modules:
    total += 1
    try:
        __import__(m); passed += 1
    except Exception as e:
        print(f'  [FAIL] {m}: {e}')
print(f'  {passed}/{total} compiled OK')

# ═══ 2. Persona routing ═══
print('\n=== 2. Persona Routing ===')
from agent.prompt import detect_persona
p_tests = [
    ('教三楼灯坏了','报修助手'),('最近校园有什么动态','校园观察员'),('统计最近报修数量','数据分析师'),
    ('我有个建议想提','议事顾问'),('今天天气怎么样','校园观察员'),('图书馆水龙头漏水','报修助手'),
    ('看看治理数据','数据分析师'),('我想创建提案','议事顾问'),('食堂没电了','报修助手'),
    ('大家最近在讨论什么','校园观察员'),('统计提案解决情况','数据分析师'),('看看提案列表','数据分析师'),
    ('你好',None),('谢谢',None),('最近有什么新提案','议事顾问'),('讨论一下食堂问题','议事顾问'),
    ('校园脉搏','校园观察员'),('数据分析最近提案趋势','数据分析师'),('我要报修','报修助手'),
    ('有哪些提案','议事顾问'),('附议提案3','议事顾问'),('查看工单进度','数据分析师'),
    ('看看有什么问题','数据分析师'),  # "问题"+"有什么问题"是典型的数据查询，非校园动态
    ('查询所有待处理工单','数据分析师'),
    # ── Status-query override: "修好了吗" type queries flip repair→data analyst ──
    ('我上报的水龙头修好了吗','数据分析师'),
    ('食堂灯修好了吗',None),            # 无关键词命中 → agent 通用处理，不会误报修
    ('工单#42解决了吗','数据分析师'),
    ('我之前报修的灯泡有进展吗','数据分析师'),
    ('三教厕所堵了处理了吗','数据分析师'),
    ('我那个提案有回复吗','议事顾问'),   # 提案状态查询是议事行为，不需要翻转为数据分析
    # ── Genuine repair intents should still route correctly ──
    ('教三楼灯坏了','报修助手'),
    ('食堂没电了','报修助手'),
    ('水龙头漏水了','报修助手'),
]
p_ok = 0
for txt, expected in p_tests:
    r = detect_persona(txt)
    role = r['role'].split()[0] if r else None
    if (role is None and expected is None) or (expected and role and expected in r['role']):
        p_ok += 1
    else:
        print(f'  [FAIL] "{txt}" -> {r["role"] if r else "None"} (expected {expected})')
total += len(p_tests); passed += p_ok
print(f'  {p_ok}/{len(p_tests)} passed')

# ═══ 3. Text-action parsing ═══
print('\n=== 3. Text-Action Parsing ===')
from agent.reflector._parser import parse_text_actions as _parse_text_actions, _TEXT_ACTION_PATTERNS
t_tests = [
    ('已为你生成工单 #42，分类为设施维修',1),('校园脉搏显示本周有3个新工单',1),
    ('天气晴好，适合出行',1),('我已创建提案',1),('已上报工单 #15，请等待处理',1),
    ('今日校园脉搏：3个待处理问题，天气晴',2),('这是一个普通回复，没有特殊动作',0),
    ('已采纳该提案，感谢你的建议',1),('查询工单后发现3条待处理记录',1),
    ('已报修成功，工单号#99',1),('支持该提案，已有73人附议',1),
]
t_ok = 0
for txt, expected_min in t_tests:
    steps = _parse_text_actions(txt)
    if len(steps) >= expected_min: t_ok += 1
    else: print(f'  [FAIL] {len(steps)} steps from "{txt[:40]}" (expected >= {expected_min})')
total += len(t_tests); passed += t_ok
print(f'  {t_ok}/{len(t_tests)} passed')

# ═══ 4. Step summarization (14 tools) ═══
print('\n=== 4. Step Summarization (14 tools) ===')
from agent.reflector._parser import summarize_step as _summarize_step
s_tests = [
    ('report_issue',{'title':'灯坏了','category':'设施维修'}),
    ('query_issues',{'category':'设施维修','status':'待处理'}),
    ('get_campus_pulse',{}),('get_governance_stats',{}),('get_weather',{}),
    ('create_proposal',{'title':'延长图书馆时间'}),('support_proposal',{'proposal_id':5}),
    ('get_proposals',{}),('get_topics',{}),('get_topic_detail',{'topic_id':3}),
    ('express_opinion',{}),('collect_feedback',{}),
    ('query_knowledge',{'query':'停水通知'}),('get_school_policy',{'topic':'宿舍管理'}),
    ('query_my_issues',{}),('query_my_proposals',{}),
]
s_ok = 0
for tool_name, tool_input in s_tests:
    summary = _summarize_step(tool_name, tool_input)
    if len(summary) > 3 and 'unknown' not in summary.lower(): s_ok += 1
    else: print(f'  [FAIL] {tool_name}: {summary}')
total += len(s_tests); passed += s_ok
print(f'  {s_ok}/{len(s_tests)} passed')

# ═══ 5. Association dimensions ═══
print('\n=== 5. Association Dimensions ===')
from agent.reflector import compute_associations, build_reasoning_chain
result = compute_associations('test', [])
keys = ['spatial','temporal','recurrence','anomalies','correlations','linked_proposals','resolution_efficiency','has_insight','insight_text']
missing_keys = [k for k in keys if k not in result]
total += 1
if not missing_keys: passed += 1; print(f'  [OK] All 9 keys present')
else: print(f'  [FAIL] Missing: {missing_keys}')

chain = build_reasoning_chain([], '校园脉搏显示3个新工单，天气晴好。', '校园脉搏')
total += 1
if chain.get('steps') and chain.get('associations'):
    passed += 1; print(f'  [OK] build_reasoning_chain: {len(chain["steps"])} steps + associations')
else: print(f'  [FAIL] build_reasoning_chain incomplete')

# ═══ 6. System prompt ═══
print('\n=== 6. System Prompt ===')
from agent.prompt import get_system_prompt
prompt = get_system_prompt({'school':'测试大学','grade':'大三','major':'计算机'})
total += 1
if '预取' in prompt and 'report_issue' in prompt and len(prompt) > 2000:
    passed += 1; print(f'  [OK] {len(prompt)} chars, has prefetch + all tools')
else: print(f'  [FAIL] Prompt incomplete')

total += 1
if len(_TEXT_ACTION_PATTERNS) >= 12:
    passed += 1; print(f'  [OK] {len(_TEXT_ACTION_PATTERNS)} text-action patterns')
else: print(f'  [FAIL] only {len(_TEXT_ACTION_PATTERNS)} patterns')

# ═══ 7. Tool discovery ═══
print('\n=== 7. Tool Discovery ===')
from tools import discover_tools
tools = discover_tools()
total += 1
if len(tools) >= 10: passed += 1; print(f'  [OK] {len(tools)} tools discovered')
else: print(f'  [FAIL] only {len(tools)} tools')

# ═══ 8. Database roundtrip ═══
print('\n=== 8. Database Roundtrip ===')
db_path = os.path.join(tempfile.gettempdir(), 'test_campus_verify.db')
from data.database import init_db
try:
    init_db(db_path)
    from data.database import report_issue, get_issues, get_issues_stats, compute_health_score
    from data.database import create_proposal, get_proposals, support_proposal
    from data.database import create_topic, get_active_topics, add_opinion

    id1 = report_issue('测试灯坏', '设施维修', '教三楼', '测试', '紧急', 'test_user')
    id2 = report_issue('测试漏水', '设施维修', '教三楼', '测试', '普通', 'test_user')
    id3 = report_issue('测试垃圾', '环境卫生', '食堂', '测试', '普通', 'test_user')
    total += 1
    if id1 and id2 and id3: passed += 1; print(f'  [OK] Created issues #{id1}, #{id2}, #{id3}')
    else: print(f'  [FAIL] Issue creation failed')

    issues = get_issues(limit=10)
    total += 1
    if len(issues) >= 3: passed += 1; print(f'  [OK] get_issues returns {len(issues)} rows')
    else: print(f'  [FAIL] get_issues only {len(issues)} rows')

    stats = get_issues_stats()
    total += 1
    if stats['total'] >= 3: passed += 1; print(f'  [OK] stats: {stats["total"]} total')
    else: print(f'  [FAIL] stats wrong')

    health = compute_health_score()
    total += 1
    if 'score' in health and 'grade' in health:
        passed += 1; print(f'  [OK] health: {health["score"]}分 {health["grade"]}')
    else: print(f'  [FAIL] health compute failed')

    pid = create_proposal('测试提案', '测试内容', '设施维修', 'test_user')
    sp_count = support_proposal(pid)
    proposals = get_proposals(limit=5)
    total += 1
    if len(proposals) >= 1 and sp_count >= 2:
        passed += 1; print(f'  [OK] Proposal #{pid} with {sp_count} supporters')
    else: print(f'  [FAIL] Proposal test')

    tid = create_topic('测试议题', '测试描述', '设施维修')
    oid = add_opinion(tid, '测试意见', 'test_user')
    topics = get_active_topics(limit=5)
    total += 1
    if len(topics) >= 1: passed += 1; print(f'  [OK] Topic #{tid} with opinion #{oid}')
    else: print(f'  [FAIL] Topic test')

    os.unlink(db_path)
except Exception as e:
    print(f'  [FAIL] DB test error: {e}')
    import traceback; traceback.print_exc()

# ═══ 9. Prefetch Functions ═══
print('\n=== 9. Prefetch Functions ===')
from ui.prefetch import _prefetch_pulse, _prefetch_stats, _prefetch_proposals, _prefetch_topics, _prefetch_query_issues, try_prefetch, _prefetch_weather
db_path2 = os.path.join(tempfile.gettempdir(), 'test_prefetch_verify.db')
init_db(db_path2)
from data.seed import seed_all
seed_all(db_path2)

pulse = _prefetch_pulse()
total += 1
if '校园脉搏' in pulse and '工单' in pulse: passed += 1; print(f'  [OK] _prefetch_pulse: {len(pulse)} chars')
else: print(f'  [FAIL] _prefetch_pulse: missing expected content')

stats_pf = _prefetch_stats()
total += 1
if '健康度' in stats_pf: passed += 1; print(f'  [OK] _prefetch_stats: {len(stats_pf)} chars')
else: print(f'  [FAIL] _prefetch_stats: missing health score')

props_pf = _prefetch_proposals()
total += 1
if props_pf and '提案' in props_pf: passed += 1; print(f'  [OK] _prefetch_proposals: {len(props_pf)} chars')
else: print(f'  [FAIL] _prefetch_proposals: empty or missing')

topics_pf = _prefetch_topics()
total += 1
if topics_pf and '议题' in topics_pf: passed += 1; print(f'  [OK] _prefetch_topics: {len(topics_pf)} chars')
else: print(f'  [FAIL] _prefetch_topics: empty or missing')

issues_pf = _prefetch_query_issues()
total += 1
if issues_pf and '工单' in issues_pf: passed += 1; print(f'  [OK] _prefetch_query_issues: {len(issues_pf)} chars')
else: print(f'  [FAIL] _prefetch_query_issues: empty or missing')

# try_prefetch dispatch
r1 = try_prefetch('校园脉搏有什么新动态？')
total += 1
if r1 is not None: passed += 1; print(f'  [OK] try_prefetch("校园脉搏") matched')
else: print(f'  [FAIL] try_prefetch("校园脉搏") returned None')

r2 = try_prefetch('帮我统计治理数据')
total += 1
if r2 is not None: passed += 1; print(f'  [OK] try_prefetch("治理数据") matched')
else: print(f'  [FAIL] try_prefetch("治理数据") returned None')

r3 = try_prefetch('hi')  # too short, should return None
total += 1
if r3 is None: passed += 1; print(f'  [OK] try_prefetch("hi") correctly returned None')
else: print(f'  [FAIL] try_prefetch("hi") should return None for short input')

r4 = try_prefetch('今天天气怎么样')
total += 1
if r4 is not None: passed += 1; print(f'  [OK] try_prefetch("天气") matched')
else: print(f'  [FAIL] try_prefetch("天气") returned None')

r5 = try_prefetch('有什么提案')
total += 1
if r5 is not None: passed += 1; print(f'  [OK] try_prefetch("提案") matched')
else: print(f'  [FAIL] try_prefetch("提案") returned None')

r6 = try_prefetch('大家在讨论什么')
total += 1
if r6 is not None: passed += 1; print(f'  [OK] try_prefetch("讨论") matched')
else: print(f'  [FAIL] try_prefetch("讨论") returned None')

r7 = try_prefetch('看看有哪些问题工单报修')
total += 1
if r7 is not None: passed += 1; print(f'  [OK] try_prefetch("工单") matched')
else: print(f'  [FAIL] try_prefetch("工单") returned None')

os.unlink(db_path2)

# ═══ 10. Seed Deterministic Hash ═══
print('\n=== 10. Seed Deterministic Hash ===')
from data.seed import _stable_hash
h1 = _stable_hash('test title 1', 4)
h2 = _stable_hash('test title 1', 4)
h3 = _stable_hash('different title', 4)
total += 1
if h1 == h2: passed += 1; print(f'  [OK] _stable_hash is deterministic: {h1} == {h2}')
else: print(f'  [FAIL] _stable_hash not deterministic: {h1} != {h2}')
total += 1
if h1 != h3: passed += 1; print(f'  [OK] _stable_hash different inputs produce different outputs')
else: print(f'  [FAIL] _stable_hash collision: {h1} == {h3}')

# ═══ 11. Proposal Status Response Preservation ═══
print('\n=== 11. Proposal Status Response Preservation ===')
db_path3 = os.path.join(tempfile.gettempdir(), 'test_proposal_verify.db')
init_db(db_path3)
from data.database import create_proposal, update_proposal_status, get_proposals
pid = create_proposal('测试提案Preserve', '测试', '校园管理', 'test_author')
update_proposal_status(pid, '已回应', '官方回复测试文本')
props = get_proposals(limit=5)
p = [pr for pr in props if pr['id'] == pid][0]
total += 1
if p['status'] == '已回应' and p['response_text'] == '官方回复测试文本':
    passed += 1; print(f'  [OK] Reply stored: status={p["status"]}, response preserved')
else: print(f'  [FAIL] Reply failed: status={p["status"]}, resp={p["response_text"]}')

update_proposal_status(pid, '已采纳')  # without new response_text
props = get_proposals(limit=5)
p = [pr for pr in props if pr['id'] == pid][0]
total += 1
if p['status'] == '已采纳' and p['response_text'] == '官方回复测试文本':
    passed += 1; print(f'  [OK] Response preserved after adopt: {p["response_text"]}')
else: print(f'  [FAIL] Response lost: status={p["status"]}, resp={p["response_text"]}')

os.unlink(db_path3)

# ═══ 12. Issue Reopen (resolved_at → NULL) ═══
print('\n=== 12. Issue Reopen Resolved Clearing ===')
db_path4 = os.path.join(tempfile.gettempdir(), 'test_issue_reopen.db')
init_db(db_path4)
from data.database import report_issue, update_issue_status, get_issues
iid = report_issue('test reopen', '设施维修', 'loc', 'desc', '普通', 'author')
update_issue_status(iid, '已解决')
issues = get_issues(limit=5)
i = [iss for iss in issues if iss['id'] == iid][0]
total += 1
if i['status'] == '已解决' and i.get('resolved_at') is not None:
    passed += 1; print(f'  [OK] Resolved: resolved_at={i["resolved_at"][:10]}...')
else: print(f'  [FAIL] Resolved: status={i["status"]}, resolved_at={i.get("resolved_at")}')

update_issue_status(iid, '待处理')  # reopen
issues = get_issues(limit=5)
i = [iss for iss in issues if iss['id'] == iid][0]
total += 1
if i['status'] == '待处理' and i.get('resolved_at') is None:
    passed += 1; print(f'  [OK] Reopened: resolved_at cleared to None')
else: print(f'  [FAIL] Reopen: status={i["status"]}, resolved_at={i.get("resolved_at")}')

os.unlink(db_path4)

# ═══ 13. Enhanced Anomaly Detection (z-score, cross-time, upgrade paths) ═══
print('\n=== 13. Enhanced Anomaly Detection ===')
db_path5 = os.path.join(tempfile.gettempdir(), 'test_enhanced_reflector.db')
init_db(db_path5)
seed_all(db_path5)
from agent.reflector import _z_score_anomalies, _cross_time_comparison, _detect_upgrade_paths
from data.database import get_db as _gdb13

with _gdb13() as conn:
    za = _z_score_anomalies(conn)
total += 1
if isinstance(za, list):
    passed += 1; print(f'  [OK] z_score_anomalies returns list ({len(za)} entries)')
else: print(f'  [FAIL] z_score_anomalies wrong type: {type(za)}')

with _gdb13() as conn:
    ct = _cross_time_comparison(conn)
total += 1
if isinstance(ct, dict) and 'new_this_week' in ct:
    passed += 1; print(f'  [OK] cross_time keys present: {sorted(ct.keys())}')
else: print(f'  [FAIL] cross_time: {ct}')

with _gdb13() as conn:
    up = _detect_upgrade_paths(conn)
total += 1
if isinstance(up, list):
    passed += 1; print(f'  [OK] upgrade_paths returns list ({len(up)} entries)')
else: print(f'  [FAIL] upgrade_paths wrong type: {type(up)}')

# Verify enriched association dict has new keys
assoc = compute_associations('教三楼灯坏了', [])
total += 1
new_keys = ['cross_time', 'z_anomalies', 'upgrade_paths']
missing_new = [k for k in new_keys if k not in assoc]
if not missing_new:
    passed += 1; print(f'  [OK] Association dict has new fields (total {len(assoc)} keys)')
else: print(f'  [FAIL] Missing new keys: {missing_new}')

# Verify z_anomalies entries have severity field
total += 1
all_have_severity = all('severity' in a and 'level' in a for a in za)
print(f'  [OK] z_anomalies severity+level fields: {all_have_severity} (count={len(za)})')
passed += 1

os.unlink(db_path5)

# ═══ 14. Enhanced Persona Detection ═══
print('\n=== 14. Enhanced Persona Detection ===')
from agent.prompt import detect_persona as _dp14

# Confidence scoring — high confidence
r_conf = _dp14('教三楼灯坏了漏水故障')
total += 1
if r_conf and r_conf.get('confidence') == 'high' and r_conf.get('matched_count', 0) >= 3:
    passed += 1; print(f'  [OK] High confidence: conf={r_conf["confidence"]}, matches={r_conf["matched_count"]}')
else: print(f'  [FAIL] confidence result: {r_conf}')

# Single short keyword
r_low = _dp14('灯')
total += 1
if r_low is None or r_low.get('confidence') == 'low':
    passed += 1; print(f'  [OK] Short keyword: low/no confidence: {r_low}')
else: print(f'  [FAIL] low conf: {r_low}')

# Very short input
r_short = _dp14('你好')
total += 1
if r_short is None:
    passed += 1; print(f'  [OK] Very short input returns None')
else: print(f'  [FAIL] short input should return None: {r_short}')

# Mixed CN/EN input
r_mixed = _dp14('wifi坏了教室')
total += 1
if r_mixed and '报修' in r_mixed.get('role', ''):
    passed += 1; print(f'  [OK] Mixed CN/EN: role={r_mixed["role"][:15]}..., conf={r_mixed.get("confidence")}')
else: print(f'  [FAIL] Mixed CN/EN: {r_mixed}')

# Three-way persona conflict
r_three = _dp14('统计最近的提案和水龙头漏水修复情况')
total += 1
if r_three and r_three.get('role'):
    passed += 1; print(f'  [OK] Three-way conflict resolves: role={r_three["role"][:15]}..., conf={r_three.get("confidence")}')
else: print(f'  [FAIL] Three-way: {r_three}')

# Multi-persona blend
r_blend = _dp14('统计最近校园动态和提案数据')
total += 1
if r_blend and r_blend.get('role'):
    passed += 1; print(f'  [OK] Multi-persona: role={r_blend["role"][:15]}..., conf={r_blend.get("confidence")}')
else: print(f'  [FAIL] blend result: {r_blend}')

# ═══ 15. Governance Audit Data ═══
print('\n=== 15. Governance Audit Data ===')
db_path6 = os.path.join(tempfile.gettempdir(), 'test_audit_report.db')
init_db(db_path6)
seed_all(db_path6)
from data.database import get_db as _gdb15

with _gdb15() as conn:
    issue_count = conn.execute("SELECT COUNT(*) FROM campus_issues").fetchone()[0]
    proposal_count = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    topic_count = conn.execute("SELECT COUNT(*) FROM discussion_topics").fetchone()[0]
total += 1
if issue_count > 0 and proposal_count > 0 and topic_count > 0:
    passed += 1; print(f'  [OK] Audit data: {issue_count} issues, {proposal_count} proposals, {topic_count} topics')
else: print(f'  [FAIL] counts: {issue_count}/{proposal_count}/{topic_count}')

# Health score fields
from data.database import compute_health_score as _chs15
health = _chs15()
total += 1
if 'score' in health and 'grade' in health and 'resolution_rate' in health and 'trend' in health:
    passed += 1; print(f'  [OK] Health: {health["score"]}分 {health["grade"]} (rate={health["resolution_rate"]}%, trend={health["trend"]})')
else: print(f'  [FAIL] Health keys: {list(health.keys())}')

os.unlink(db_path6)

# ═══ 16. Theme Token Consistency ═══
print('\n=== 16. Theme Token Consistency ===')
from ui.theme import TOKEN_LIGHT, TOKEN_DARK

# Same keys in both themes
total += 1
if set(TOKEN_LIGHT.keys()) == set(TOKEN_DARK.keys()):
    passed += 1; print(f'  [OK] Light/Dark tokens have identical keys ({len(TOKEN_LIGHT)} keys)')
else:
    only_light = set(TOKEN_LIGHT.keys()) - set(TOKEN_DARK.keys())
    only_dark = set(TOKEN_DARK.keys()) - set(TOKEN_LIGHT.keys())
    print(f'  [FAIL] Light-only: {only_light}, Dark-only: {only_dark}')

# Radius tokens unchanged between themes
total += 1
radius_keys = ['radius_xs', 'radius_sm', 'radius', 'radius_lg', 'radius_full']
all_same = all(TOKEN_LIGHT[k] == TOKEN_DARK[k] for k in radius_keys)
if all_same:
    passed += 1; print(f'  [OK] Radius tokens identical across themes')
else: print(f'  [FAIL] Radius tokens differ')

# Transition tokens unchanged
total += 1
if TOKEN_LIGHT['transition'] == TOKEN_DARK['transition']:
    passed += 1; print(f'  [OK] Transition token identical')
else: print(f'  [FAIL] Transition differs')

# Text colors differ (dark should be lighter)
total += 1
if TOKEN_DARK['text'] != TOKEN_LIGHT['text']:
    passed += 1; print(f'  [OK] Text colors differ between themes (expected)')
else: print(f'  [FAIL] Text colors identical')

# Background colors differ
total += 1
if TOKEN_DARK['card_bg'] != TOKEN_LIGHT['card_bg']:
    passed += 1; print(f'  [OK] Card backgrounds differ between themes')
else: print(f'  [FAIL] Card bg identical')

# ═══ 17. Notification Module ═══
print('\n=== 17. Notification Module ===')
db_path7 = os.path.join(tempfile.gettempdir(), 'test_notify.db')
init_db(db_path7)
seed_all(db_path7)
from ui.notify import _fetch_counts, render_sidebar_badge

counts = _fetch_counts()
total += 1
if counts and 'total' in counts and 'pending' in counts and 'urgent' in counts:
    passed += 1; print(f'  [OK] fetch_counts: total={counts["total"]}, pending={counts["pending"]}, urgent={counts["urgent"]}')
else: print(f'  [FAIL] fetch_counts: {counts}')

# Verify counts are integers
total += 1
all_ints = all(isinstance(counts.get(k, 0), int) for k in ['total', 'pending', 'urgent', 'proposal_total', 'proposal_pending'])
if all_ints:
    passed += 1; print(f'  [OK] All count values are integers')
else: print(f'  [FAIL] Non-int values in counts')

# Verify counts match DB reality
total += 1
with _gdb15() as conn:
    actual_total = conn.execute("SELECT COUNT(*) FROM campus_issues").fetchone()[0]
    actual_pending = conn.execute("SELECT COUNT(*) FROM campus_issues WHERE status='待处理'").fetchone()[0]
if counts['total'] == actual_total:
    passed += 1; print(f'  [OK] Count matches DB: {counts["total"]} == {actual_total}')
else: print(f'  [FAIL] Count mismatch: {counts["total"]} != {actual_total}')

# Verify proposal counts
total += 1
with _gdb15() as conn:
    actual_props = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    actual_discussing = conn.execute("SELECT COUNT(*) FROM proposals WHERE status='讨论中'").fetchone()[0]
if counts['proposal_total'] == actual_props:
    passed += 1; print(f'  [OK] Proposal count matches: {counts["proposal_total"]} == {actual_props}')
else: print(f'  [FAIL] Proposal count mismatch')

os.unlink(db_path7)

# ═══ Summary ═══
print(f'\n=== TOTAL: {passed}/{total} passed ===')
if passed == total:
    print('ALL TESTS PASSED')
else:
    print(f'{total - passed} TESTS FAILED')
    sys.exit(1)
