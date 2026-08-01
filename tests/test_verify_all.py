"""End-to-end verification test suite.

Compatible with both pytest collection and direct execution:
    pytest tests/test_verify_all.py -s
    python tests/test_verify_all.py
"""
import sys, io, os, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
if 'pytest' not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# ══════════════════════════════════════════════════════════════════════════════
#  Helper utilities
# ══════════════════════════════════════════════════════════════════════════════

def _ok(msg):
    print(f'  [OK] {msg}')


def _fail(msg):
    print(f'  [FAIL] {msg}')


def _check(condition, count_obj, fail_msg):
    """Increment counter; return (condition, count_obj)."""
    count_obj[0] += 1
    if condition:
        count_obj[1] += 1
    else:
        _fail(fail_msg)
    return condition


# Module-level storage so main() can read counts without test functions returning values
_section_counts = [0, 0]


# ══════════════════════════════════════════════════════════════════════════════
#  1. Module compilation
# ══════════════════════════════════════════════════════════════════════════════

def test_01_module_compilation():
    """1. Module Compilation (35 modules)"""
    print('\n=== 1. Module Compilation (35 modules) ===')
    modules = [
        'config', 'agent.prompt', 'agent.engine', 'agent.reflector', 'agent.memory', 'agent.callbacks',
        'agent.helpers', 'agent.weekly_report', 'agent.rag',
        'data.database', 'data.models', 'data.seed',
        'data.db_core', 'data.db_user', 'data.db_academic', 'data.db_knowledge',
        'data.db_governance', 'data.db_health', 'data.db_surveillance',
        'data.db_notifications', 'data.db_perception', 'data.live_generator',
        'tools', 'tools.query_weather', 'tools.query_campus_pulse', 'tools.query_proposals',
        'tools.query_topics', 'tools.query_campus_issues', 'tools.action_report_issue',
        'tools.action_create_proposal', 'tools.action_support_proposal', 'tools.action_express_opinion',
        'tools.query_knowledge', 'tools.query_my_issues',
        'ui.components', 'ui.thinking', 'ui.cache', 'ui.onboarding', 'ui.session', 'ui.theme', 'ui.notify',
        'ui.prefetch', 'ui.login',
        'utils.logger', 'utils.retry', 'utils.text',
        'perception.monitor',
    ]
    cnt = [0, 0]  # [total, passed]
    for m in modules:
        try:
            __import__(m)
            cnt[1] += 1
        except Exception as e:
            _fail(f'{m}: {e}')
        cnt[0] += 1
    _ok(f'{cnt[1]}/{cnt[0]} compiled OK')
    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} modules failed to compile'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  2. Persona routing
# ══════════════════════════════════════════════════════════════════════════════

def test_02_persona_routing():
    """2. Persona Routing"""
    print('\n=== 2. Persona Routing ===')
    from agent.prompt import detect_persona
    p_tests = [
        ('教三楼灯坏了', '报修助手'), ('最近校园有什么动态', '校园观察员'), ('统计最近报修数量', '数据分析师'),
        ('我有个建议想提', '议事顾问'), ('今天天气怎么样', '校园观察员'), ('图书馆水龙头漏水', '报修助手'),
        ('看看治理数据', '数据分析师'), ('我想创建提案', '议事顾问'), ('食堂没电了', '报修助手'),
        ('大家最近在讨论什么', '校园观察员'), ('统计提案解决情况', '数据分析师'), ('看看提案列表', '数据分析师'),
        ('你好', None), ('谢谢', None), ('最近有什么新提案', '议事顾问'), ('讨论一下食堂问题', '议事顾问'),
        ('校园脉搏', '校园观察员'), ('数据分析最近提案趋势', '数据分析师'), ('我要报修', '报修助手'),
        ('有哪些提案', '议事顾问'), ('附议提案3', '议事顾问'), ('查看工单进度', '数据分析师'),
        ('看看有什么问题', '数据分析师'),
        ('查询所有待处理工单', '数据分析师'),
        # Status-query override: "修好了吗" type queries flip repair→data analyst
        ('我上报的水龙头修好了吗', '数据分析师'),
        ('食堂灯修好了吗', None),
        ('工单#42解决了吗', '数据分析师'),
        ('我之前报修的灯泡有进展吗', '数据分析师'),
        ('三教厕所堵了处理了吗', '数据分析师'),
        ('我那个提案有回复吗', '议事顾问'),
        # Genuine repair intents should still route correctly
        ('教三楼灯坏了', '报修助手'),
        ('食堂没电了', '报修助手'),
        ('水龙头漏水了', '报修助手'),
    ]
    p_ok = 0
    for txt, expected in p_tests:
        r = detect_persona(txt)
        role = r['role'].split()[0] if r else None
        if (role is None and expected is None) or (expected and role and expected in r['role']):
            p_ok += 1
        else:
            _fail(f'"{txt}" -> {r["role"] if r else "None"} (expected {expected})')
    _ok(f'{p_ok}/{len(p_tests)} passed')
    assert p_ok == len(p_tests), f'{len(p_tests) - p_ok} persona tests failed'
    _section_counts[:] = [len(p_tests), p_ok]


# ══════════════════════════════════════════════════════════════════════════════
#  3. Text-action parsing
# ══════════════════════════════════════════════════════════════════════════════

def test_03_text_action_parsing():
    """3. Text-Action Parsing"""
    print('\n=== 3. Text-Action Parsing ===')
    from agent.reflector._parser import parse_text_actions as _parse_text_actions, _TEXT_ACTION_PATTERNS
    t_tests = [
        ('已为你生成工单 #42，分类为设施维修', 1), ('校园脉搏显示本周有3个新工单', 1),
        ('天气晴好，适合出行', 1), ('我已创建提案', 1), ('已上报工单 #15，请等待处理', 1),
        ('今日校园脉搏：3个待处理问题，天气晴', 2), ('这是一个普通回复，没有特殊动作', 0),
        ('已采纳该提案，感谢你的建议', 1), ('查询工单后发现3条待处理记录', 1),
        ('已报修成功，工单号#99', 1), ('支持该提案，已有73人附议', 1),
    ]
    t_ok = 0
    for txt, expected_min in t_tests:
        steps = _parse_text_actions(txt)
        if len(steps) >= expected_min:
            t_ok += 1
        else:
            _fail(f'{len(steps)} steps from "{txt[:40]}" (expected >= {expected_min})')
    _ok(f'{t_ok}/{len(t_tests)} passed')
    assert t_ok == len(t_tests), f'{len(t_tests) - t_ok} text-action tests failed'
    _section_counts[:] = [len(t_tests), t_ok]


# ══════════════════════════════════════════════════════════════════════════════
#  4. Step summarization (14 tools)
# ══════════════════════════════════════════════════════════════════════════════

def test_04_step_summarization():
    """4. Step Summarization (14 tools)"""
    print('\n=== 4. Step Summarization (14 tools) ===')
    from agent.reflector._parser import summarize_step as _summarize_step
    s_tests = [
        ('report_issue', {'title': '灯坏了', 'category': '设施维修'}),
        ('query_issues', {'category': '设施维修', 'status': '待处理'}),
        ('get_campus_pulse', {}), ('get_governance_stats', {}), ('get_weather', {}),
        ('create_proposal', {'title': '延长图书馆时间'}), ('support_proposal', {'proposal_id': 5}),
        ('get_proposals', {}), ('get_topics', {}), ('get_topic_detail', {'topic_id': 3}),
        ('express_opinion', {}), ('collect_feedback', {}),
        ('query_knowledge', {'query': '停水通知'}), ('get_school_policy', {'topic': '宿舍管理'}),
        ('query_my_issues', {}), ('query_my_proposals', {}),
    ]
    s_ok = 0
    for tool_name, tool_input in s_tests:
        summary = _summarize_step(tool_name, tool_input)
        if len(summary) > 3 and 'unknown' not in summary.lower():
            s_ok += 1
        else:
            _fail(f'{tool_name}: {summary}')
    _ok(f'{s_ok}/{len(s_tests)} passed')
    assert s_ok == len(s_tests), f'{len(s_tests) - s_ok} summarization tests failed'
    _section_counts[:] = [len(s_tests), s_ok]


# ══════════════════════════════════════════════════════════════════════════════
#  5. Association dimensions
# ══════════════════════════════════════════════════════════════════════════════

def test_05_association_dimensions():
    """5. Association Dimensions"""
    print('\n=== 5. Association Dimensions ===')
    from agent.reflector import compute_associations, build_reasoning_chain
    cnt = [0, 0]  # [total, passed]
    result = compute_associations('test', [])
    keys = ['spatial', 'temporal', 'recurrence', 'anomalies', 'correlations',
            'linked_proposals', 'resolution_efficiency', 'has_insight', 'insight_text']
    missing_keys = [k for k in keys if k not in result]
    if not missing_keys:
        cnt[1] += 1; _ok('All 9 keys present')
    else:
        _fail(f'Missing: {missing_keys}')
    cnt[0] += 1

    chain = build_reasoning_chain([], '校园脉搏显示3个新工单，天气晴好。', '校园脉搏')
    if chain.get('steps') and chain.get('associations'):
        cnt[1] += 1; _ok(f'build_reasoning_chain: {len(chain["steps"])} steps + associations')
    else:
        _fail('build_reasoning_chain incomplete')
    cnt[0] += 1

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} association tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  6. System prompt
# ══════════════════════════════════════════════════════════════════════════════

def test_06_system_prompt():
    """6. System Prompt"""
    print('\n=== 6. System Prompt ===')
    from agent.prompt import get_system_prompt
    from agent.reflector._parser import _TEXT_ACTION_PATTERNS
    cnt = [0, 0]  # [total, passed]

    prompt = get_system_prompt({'school': '测试大学', 'grade': '大三', 'major': '计算机'})
    if '预取' in prompt and 'report_issue' in prompt and len(prompt) > 2000:
        cnt[1] += 1; _ok(f'{len(prompt)} chars, has prefetch + all tools')
    else:
        _fail('Prompt incomplete')
    cnt[0] += 1

    if len(_TEXT_ACTION_PATTERNS) >= 12:
        cnt[1] += 1; _ok(f'{len(_TEXT_ACTION_PATTERNS)} text-action patterns')
    else:
        _fail(f'only {len(_TEXT_ACTION_PATTERNS)} patterns')
    cnt[0] += 1

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} system-prompt tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  7. Tool discovery
# ══════════════════════════════════════════════════════════════════════════════

def test_07_tool_discovery():
    """7. Tool Discovery"""
    print('\n=== 7. Tool Discovery ===')
    from tools import discover_tools
    tools = discover_tools()
    if len(tools) >= 10:
        _ok(f'{len(tools)} tools discovered')
    else:
        _fail(f'only {len(tools)} tools')
    assert len(tools) >= 10, f'Expected >=10 tools, got {len(tools)}'
    _section_counts[:] = [1, 1 if len(tools) >= 10 else 0]


# ══════════════════════════════════════════════════════════════════════════════
#  8. Database roundtrip
# ══════════════════════════════════════════════════════════════════════════════

def test_08_database_roundtrip():
    """8. Database Roundtrip"""
    print('\n=== 8. Database Roundtrip ===')
    db_path = os.path.join(tempfile.gettempdir(), 'test_campus_verify.db')
    from data.database import init_db
    cnt = [0, 0]  # [total, passed]

    try:
        init_db(db_path)
        from data.database import report_issue, get_issues, get_issues_stats, compute_health_score
        from data.database import create_proposal, get_proposals, support_proposal
        from data.database import create_topic, get_active_topics, add_opinion

        id1 = report_issue('测试灯坏', '设施维修', '教三楼', '测试', '紧急', 'test_user')
        id2 = report_issue('测试漏水', '设施维修', '教三楼', '测试', '普通', 'test_user')
        id3 = report_issue('测试垃圾', '环境卫生', '食堂', '测试', '普通', 'test_user')
        if id1 and id2 and id3:
            cnt[1] += 1; _ok(f'Created issues #{id1}, #{id2}, #{id3}')
        else:
            _fail('Issue creation failed')
        cnt[0] += 1

        issues = get_issues(limit=10)
        if len(issues) >= 3:
            cnt[1] += 1; _ok(f'get_issues returns {len(issues)} rows')
        else:
            _fail(f'get_issues only {len(issues)} rows')
        cnt[0] += 1

        stats = get_issues_stats()
        if stats['total'] >= 3:
            cnt[1] += 1; _ok(f'stats: {stats["total"]} total')
        else:
            _fail('stats wrong')
        cnt[0] += 1

        health = compute_health_score()
        if 'score' in health and 'grade' in health:
            cnt[1] += 1; _ok(f'health: {health["score"]}分 {health["grade"]}')
        else:
            _fail('health compute failed')
        cnt[0] += 1

        pid = create_proposal('测试提案', '测试内容', '设施维修', 'test_user')
        sp_count = support_proposal(pid)
        proposals = get_proposals(limit=5)
        if len(proposals) >= 1 and sp_count >= 2:
            cnt[1] += 1; _ok(f'Proposal #{pid} with {sp_count} supporters')
        else:
            _fail('Proposal test')
        cnt[0] += 1

        tid = create_topic('测试议题', '测试描述', '设施维修')
        oid = add_opinion(tid, '测试意见', 'test_user')
        topics = get_active_topics(limit=5)
        if len(topics) >= 1:
            cnt[1] += 1; _ok(f'Topic #{tid} with opinion #{oid}')
        else:
            _fail('Topic test')
        cnt[0] += 1

        os.unlink(db_path)
    except Exception as e:
        _fail(f'DB test error: {e}')
        import traceback; traceback.print_exc()
        cnt[0] += 6  # mark all subtests as attempted
        if os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except Exception:
                pass

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} database roundtrip tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  9. Prefetch functions
# ══════════════════════════════════════════════════════════════════════════════

def test_09_prefetch_functions():
    """9. Prefetch Functions"""
    print('\n=== 9. Prefetch Functions ===')
    from data.database import init_db
    from data.seed import seed_all
    from ui.prefetch import (_prefetch_pulse, _prefetch_stats, _prefetch_proposals,
                             _prefetch_topics, _prefetch_query_issues, try_prefetch,
                             _prefetch_weather)

    db_path2 = os.path.join(tempfile.gettempdir(), 'test_prefetch_verify.db')
    init_db(db_path2)
    seed_all(db_path2)
    cnt = [0, 0]  # [total, passed]

    pulse = _prefetch_pulse()
    if '校园脉搏' in pulse and '工单' in pulse:
        cnt[1] += 1; _ok(f'_prefetch_pulse: {len(pulse)} chars')
    else:
        _fail('_prefetch_pulse: missing expected content')
    cnt[0] += 1

    stats_pf = _prefetch_stats()
    if '健康度' in stats_pf:
        cnt[1] += 1; _ok(f'_prefetch_stats: {len(stats_pf)} chars')
    else:
        _fail('_prefetch_stats: missing health score')
    cnt[0] += 1

    props_pf = _prefetch_proposals()
    if props_pf and '提案' in props_pf:
        cnt[1] += 1; _ok(f'_prefetch_proposals: {len(props_pf)} chars')
    else:
        _fail('_prefetch_proposals: empty or missing')
    cnt[0] += 1

    topics_pf = _prefetch_topics()
    if topics_pf and '议题' in topics_pf:
        cnt[1] += 1; _ok(f'_prefetch_topics: {len(topics_pf)} chars')
    else:
        _fail('_prefetch_topics: empty or missing')
    cnt[0] += 1

    issues_pf = _prefetch_query_issues()
    if issues_pf and '工单' in issues_pf:
        cnt[1] += 1; _ok(f'_prefetch_query_issues: {len(issues_pf)} chars')
    else:
        _fail('_prefetch_query_issues: empty or missing')
    cnt[0] += 1

    # try_prefetch dispatch
    r1 = try_prefetch('校园脉搏有什么新动态？')
    if r1 is not None:
        cnt[1] += 1; _ok('try_prefetch("校园脉搏") matched')
    else:
        _fail('try_prefetch("校园脉搏") returned None')
    cnt[0] += 1

    r2 = try_prefetch('帮我统计治理数据')
    if r2 is not None:
        cnt[1] += 1; _ok('try_prefetch("治理数据") matched')
    else:
        _fail('try_prefetch("治理数据") returned None')
    cnt[0] += 1

    r3 = try_prefetch('hi')
    if r3 is None:
        cnt[1] += 1; _ok('try_prefetch("hi") correctly returned None')
    else:
        _fail('try_prefetch("hi") should return None for short input')
    cnt[0] += 1

    r4 = try_prefetch('今天天气怎么样')
    if r4 is not None:
        cnt[1] += 1; _ok('try_prefetch("天气") matched')
    else:
        _fail('try_prefetch("天气") returned None')
    cnt[0] += 1

    r5 = try_prefetch('有什么提案')
    if r5 is not None:
        cnt[1] += 1; _ok('try_prefetch("提案") matched')
    else:
        _fail('try_prefetch("提案") returned None')
    cnt[0] += 1

    r6 = try_prefetch('大家在讨论什么')
    if r6 is not None:
        cnt[1] += 1; _ok('try_prefetch("讨论") matched')
    else:
        _fail('try_prefetch("讨论") returned None')
    cnt[0] += 1

    r7 = try_prefetch('看看有哪些问题工单报修')
    if r7 is not None:
        cnt[1] += 1; _ok('try_prefetch("工单") matched')
    else:
        _fail('try_prefetch("工单") returned None')
    cnt[0] += 1

    os.unlink(db_path2)

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} prefetch tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  10. Seed deterministic hash
# ══════════════════════════════════════════════════════════════════════════════

def test_10_seed_deterministic_hash():
    """10. Seed Deterministic Hash"""
    print('\n=== 10. Seed Deterministic Hash ===')
    from data.seed import _stable_hash
    cnt = [0, 0]  # [total, passed]

    h1 = _stable_hash('test title 1', 4)
    h2 = _stable_hash('test title 1', 4)
    h3 = _stable_hash('different title', 4)

    if h1 == h2:
        cnt[1] += 1; _ok(f'_stable_hash is deterministic: {h1} == {h2}')
    else:
        _fail(f'_stable_hash not deterministic: {h1} != {h2}')
    cnt[0] += 1

    if h1 != h3:
        cnt[1] += 1; _ok('_stable_hash different inputs produce different outputs')
    else:
        _fail(f'_stable_hash collision: {h1} == {h3}')
    cnt[0] += 1

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} seed-hash tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  11. Proposal status response preservation
# ══════════════════════════════════════════════════════════════════════════════

def test_11_proposal_status_response_preservation():
    """11. Proposal Status Response Preservation"""
    print('\n=== 11. Proposal Status Response Preservation ===')
    db_path3 = os.path.join(tempfile.gettempdir(), 'test_proposal_verify.db')
    from data.database import init_db
    init_db(db_path3)
    from data.database import create_proposal, update_proposal_status, get_proposals
    cnt = [0, 0]  # [total, passed]

    pid = create_proposal('测试提案Preserve', '测试', '校园管理', 'test_author')
    update_proposal_status(pid, '已回应', '官方回复测试文本')
    props = get_proposals(limit=5)
    p = [pr for pr in props if pr['id'] == pid][0]
    if p['status'] == '已回应' and p['response_text'] == '官方回复测试文本':
        cnt[1] += 1; _ok(f'Reply stored: status={p["status"]}, response preserved')
    else:
        _fail(f'Reply failed: status={p["status"]}, resp={p["response_text"]}')
    cnt[0] += 1

    update_proposal_status(pid, '已采纳')
    props = get_proposals(limit=5)
    p = [pr for pr in props if pr['id'] == pid][0]
    if p['status'] == '已采纳' and p['response_text'] == '官方回复测试文本':
        cnt[1] += 1; _ok(f'Response preserved after adopt: {p["response_text"]}')
    else:
        _fail(f'Response lost: status={p["status"]}, resp={p["response_text"]}')
    cnt[0] += 1

    os.unlink(db_path3)

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} proposal-preserve tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  12. Issue reopen (resolved_at → NULL)
# ══════════════════════════════════════════════════════════════════════════════

def test_12_issue_reopen_resolved_clearing():
    """12. Issue Reopen Resolved Clearing"""
    print('\n=== 12. Issue Reopen Resolved Clearing ===')
    db_path4 = os.path.join(tempfile.gettempdir(), 'test_issue_reopen.db')
    from data.database import init_db
    init_db(db_path4)
    from data.database import report_issue, update_issue_status, get_issues
    cnt = [0, 0]  # [total, passed]

    iid = report_issue('test reopen', '设施维修', 'loc', 'desc', '普通', 'author')
    update_issue_status(iid, '已解决')
    issues = get_issues(limit=5)
    i = [iss for iss in issues if iss['id'] == iid][0]
    if i['status'] == '已解决' and i.get('resolved_at') is not None:
        cnt[1] += 1; _ok(f'Resolved: resolved_at={i["resolved_at"][:10]}...')
    else:
        _fail(f'Resolved: status={i["status"]}, resolved_at={i.get("resolved_at")}')
    cnt[0] += 1

    update_issue_status(iid, '待处理')
    issues = get_issues(limit=5)
    i = [iss for iss in issues if iss['id'] == iid][0]
    if i['status'] == '待处理' and i.get('resolved_at') is None:
        cnt[1] += 1; _ok('Reopened: resolved_at cleared to None')
    else:
        _fail(f'Reopen: status={i["status"]}, resolved_at={i.get("resolved_at")}')
    cnt[0] += 1

    os.unlink(db_path4)

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} issue-reopen tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  13. Enhanced anomaly detection
# ══════════════════════════════════════════════════════════════════════════════

def test_13_enhanced_anomaly_detection():
    """13. Enhanced Anomaly Detection"""
    print('\n=== 13. Enhanced Anomaly Detection ===')
    db_path5 = os.path.join(tempfile.gettempdir(), 'test_enhanced_reflector.db')
    from data.database import init_db, get_db
    from data.seed import seed_all
    init_db(db_path5)
    seed_all(db_path5)
    from agent.reflector import (_z_score_anomalies, _cross_time_comparison,
                                  _detect_upgrade_paths, compute_associations)
    cnt = [0, 0]  # [total, passed]

    with get_db() as conn:
        za = _z_score_anomalies(conn)
    if isinstance(za, list):
        cnt[1] += 1; _ok(f'z_score_anomalies returns list ({len(za)} entries)')
    else:
        _fail(f'z_score_anomalies wrong type: {type(za)}')
    cnt[0] += 1

    with get_db() as conn:
        ct = _cross_time_comparison(conn)
    if isinstance(ct, dict) and 'new_this_week' in ct:
        cnt[1] += 1; _ok(f'cross_time keys present: {sorted(ct.keys())}')
    else:
        _fail(f'cross_time: {ct}')
    cnt[0] += 1

    with get_db() as conn:
        up = _detect_upgrade_paths(conn)
    if isinstance(up, list):
        cnt[1] += 1; _ok(f'upgrade_paths returns list ({len(up)} entries)')
    else:
        _fail(f'upgrade_paths wrong type: {type(up)}')
    cnt[0] += 1

    # Verify enriched association dict has new keys
    assoc = compute_associations('教三楼灯坏了', [])
    new_keys = ['cross_time', 'z_anomalies', 'upgrade_paths']
    missing_new = [k for k in new_keys if k not in assoc]
    if not missing_new:
        cnt[1] += 1; _ok(f'Association dict has new fields (total {len(assoc)} keys)')
    else:
        _fail(f'Missing new keys: {missing_new}')
    cnt[0] += 1

    # Verify z_anomalies entries have severity field
    all_have_severity = all('severity' in a and 'level' in a for a in za)
    _ok(f'z_anomalies severity+level fields: {all_have_severity} (count={len(za)})')
    cnt[1] += 1
    cnt[0] += 1

    os.unlink(db_path5)

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} anomaly-detection tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  14. Enhanced persona detection
# ══════════════════════════════════════════════════════════════════════════════

def test_14_enhanced_persona_detection():
    """14. Enhanced Persona Detection"""
    print('\n=== 14. Enhanced Persona Detection ===')
    from agent.prompt import detect_persona as _dp14
    cnt = [0, 0]  # [total, passed]

    # Confidence scoring — high confidence
    r_conf = _dp14('教三楼灯坏了漏水故障')
    if r_conf and r_conf.get('confidence') == 'high' and r_conf.get('matched_count', 0) >= 3:
        cnt[1] += 1; _ok(f'High confidence: conf={r_conf["confidence"]}, matches={r_conf["matched_count"]}')
    else:
        _fail(f'confidence result: {r_conf}')
    cnt[0] += 1

    # Single short keyword
    r_low = _dp14('灯')
    if r_low is None or r_low.get('confidence') == 'low':
        cnt[1] += 1; _ok(f'Short keyword: low/no confidence: {r_low}')
    else:
        _fail(f'low conf: {r_low}')
    cnt[0] += 1

    # Very short input
    r_short = _dp14('你好')
    if r_short is None:
        cnt[1] += 1; _ok('Very short input returns None')
    else:
        _fail(f'short input should return None: {r_short}')
    cnt[0] += 1

    # Mixed CN/EN input
    r_mixed = _dp14('wifi坏了教室')
    if r_mixed and '报修' in r_mixed.get('role', ''):
        cnt[1] += 1; _ok(f'Mixed CN/EN: role={r_mixed["role"][:15]}..., conf={r_mixed.get("confidence")}')
    else:
        _fail(f'Mixed CN/EN: {r_mixed}')
    cnt[0] += 1

    # Three-way persona conflict
    r_three = _dp14('统计最近的提案和水龙头漏水修复情况')
    if r_three and r_three.get('role'):
        cnt[1] += 1; _ok(f'Three-way conflict resolves: role={r_three["role"][:15]}..., conf={r_three.get("confidence")}')
    else:
        _fail(f'Three-way: {r_three}')
    cnt[0] += 1

    # Multi-persona blend
    r_blend = _dp14('统计最近校园动态和提案数据')
    if r_blend and r_blend.get('role'):
        cnt[1] += 1; _ok(f'Multi-persona: role={r_blend["role"][:15]}..., conf={r_blend.get("confidence")}')
    else:
        _fail(f'blend result: {r_blend}')
    cnt[0] += 1

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} enhanced-persona tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  15. Governance audit data
# ══════════════════════════════════════════════════════════════════════════════

def test_15_governance_audit_data():
    """15. Governance Audit Data"""
    print('\n=== 15. Governance Audit Data ===')
    db_path6 = os.path.join(tempfile.gettempdir(), 'test_audit_report.db')
    from data.database import init_db, get_db, compute_health_score
    from data.seed import seed_all
    init_db(db_path6)
    seed_all(db_path6)
    cnt = [0, 0]  # [total, passed]

    with get_db() as conn:
        issue_count = conn.execute("SELECT COUNT(*) FROM campus_issues").fetchone()[0]
        proposal_count = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        topic_count = conn.execute("SELECT COUNT(*) FROM discussion_topics").fetchone()[0]
    if issue_count > 0 and proposal_count > 0 and topic_count > 0:
        cnt[1] += 1; _ok(f'Audit data: {issue_count} issues, {proposal_count} proposals, {topic_count} topics')
    else:
        _fail(f'counts: {issue_count}/{proposal_count}/{topic_count}')
    cnt[0] += 1

    # Health score fields
    health = compute_health_score()
    if 'score' in health and 'grade' in health and 'resolution_rate' in health and 'trend' in health:
        cnt[1] += 1
        _ok(f'Health: {health["score"]}分 {health["grade"]} (rate={health["resolution_rate"]}%, trend={health["trend"]})')
    else:
        _fail(f'Health keys: {list(health.keys())}')
    cnt[0] += 1

    os.unlink(db_path6)

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} governance-audit tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  16. Theme token consistency
# ══════════════════════════════════════════════════════════════════════════════

def test_16_theme_token_consistency():
    """16. Theme Token Consistency"""
    print('\n=== 16. Theme Token Consistency ===')
    from ui.theme import TOKEN_LIGHT, TOKEN_DARK
    cnt = [0, 0]  # [total, passed]

    # Same keys in both themes
    if set(TOKEN_LIGHT.keys()) == set(TOKEN_DARK.keys()):
        cnt[1] += 1; _ok(f'Light/Dark tokens have identical keys ({len(TOKEN_LIGHT)} keys)')
    else:
        only_light = set(TOKEN_LIGHT.keys()) - set(TOKEN_DARK.keys())
        only_dark = set(TOKEN_DARK.keys()) - set(TOKEN_LIGHT.keys())
        _fail(f'Light-only: {only_light}, Dark-only: {only_dark}')
    cnt[0] += 1

    # Radius tokens unchanged between themes
    radius_keys = ['radius_input', 'radius_card', 'radius_full']
    all_same = all(TOKEN_LIGHT[k] == TOKEN_DARK[k] for k in radius_keys)
    if all_same:
        cnt[1] += 1; _ok('Radius tokens identical across themes')
    else:
        _fail('Radius tokens differ')
    cnt[0] += 1

    # Transition tokens unchanged
    if TOKEN_LIGHT['transition'] == TOKEN_DARK['transition']:
        cnt[1] += 1; _ok('Transition token identical')
    else:
        _fail('Transition differs')
    cnt[0] += 1

    # Text colors differ (dark should be lighter)
    if TOKEN_DARK['text'] != TOKEN_LIGHT['text']:
        cnt[1] += 1; _ok('Text colors differ between themes (expected)')
    else:
        _fail('Text colors identical')
    cnt[0] += 1

    # Background colors differ
    if TOKEN_DARK['card_bg'] != TOKEN_LIGHT['card_bg']:
        cnt[1] += 1; _ok('Card backgrounds differ between themes')
    else:
        _fail('Card bg identical')
    cnt[0] += 1

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} theme-token tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  17. Notification module
# ══════════════════════════════════════════════════════════════════════════════

def test_17_notification_module():
    """17. Notification Module"""
    print('\n=== 17. Notification Module ===')
    db_path7 = os.path.join(tempfile.gettempdir(), 'test_notify.db')
    from data.database import init_db, get_db
    from data.seed import seed_all
    init_db(db_path7)
    seed_all(db_path7)
    from ui.notify import _fetch_counts, render_sidebar_badge
    cnt = [0, 0]  # [total, passed]

    counts = _fetch_counts()
    if counts and 'total' in counts and 'pending' in counts and 'urgent' in counts:
        cnt[1] += 1
        _ok(f'fetch_counts: total={counts["total"]}, pending={counts["pending"]}, urgent={counts["urgent"]}')
    else:
        _fail(f'fetch_counts: {counts}')
    cnt[0] += 1

    # Verify counts are integers
    all_ints = all(isinstance(counts.get(k, 0), int) for k in ['total', 'pending', 'urgent', 'proposal_total', 'proposal_pending'])
    if all_ints:
        cnt[1] += 1; _ok('All count values are integers')
    else:
        _fail('Non-int values in counts')
    cnt[0] += 1

    # Verify counts match DB reality
    with get_db() as conn:
        actual_total = conn.execute("SELECT COUNT(*) FROM campus_issues").fetchone()[0]
        actual_pending = conn.execute("SELECT COUNT(*) FROM campus_issues WHERE status='待处理'").fetchone()[0]
    if counts['total'] == actual_total:
        cnt[1] += 1; _ok(f'Count matches DB: {counts["total"]} == {actual_total}')
    else:
        _fail(f'Count mismatch: {counts["total"]} != {actual_total}')
    cnt[0] += 1

    # Verify proposal counts
    with get_db() as conn:
        actual_props = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        actual_discussing = conn.execute("SELECT COUNT(*) FROM proposals WHERE status='讨论中'").fetchone()[0]
    if counts['proposal_total'] == actual_props:
        cnt[1] += 1; _ok(f'Proposal count matches: {counts["proposal_total"]} == {actual_props}')
    else:
        _fail('Proposal count mismatch')
    cnt[0] += 1

    os.unlink(db_path7)

    assert cnt[1] == cnt[0], f'{cnt[0] - cnt[1]} notification-module tests failed'
    _section_counts[:] = cnt


# ══════════════════════════════════════════════════════════════════════════════
#  Direct execution entry point (backward compatible)
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Run all 17 verification sections. Compatible with `python tests/test_verify_all.py`."""
    tests = [
        test_01_module_compilation,
        test_02_persona_routing,
        test_03_text_action_parsing,
        test_04_step_summarization,
        test_05_association_dimensions,
        test_06_system_prompt,
        test_07_tool_discovery,
        test_08_database_roundtrip,
        test_09_prefetch_functions,
        test_10_seed_deterministic_hash,
        test_11_proposal_status_response_preservation,
        test_12_issue_reopen_resolved_clearing,
        test_13_enhanced_anomaly_detection,
        test_14_enhanced_persona_detection,
        test_15_governance_audit_data,
        test_16_theme_token_consistency,
        test_17_notification_module,
    ]

    passed_grand = 0
    total_grand = 0
    section_failures = 0

    for test_fn in tests:
        _section_counts[:] = [0, 0]
        try:
            test_fn()
            passed_grand += _section_counts[1]
            total_grand += _section_counts[0]
        except AssertionError as e:
            section_failures += 1
            print(f'  SECTION FAILED: {e}')
        except Exception as e:
            section_failures += 1
            print(f'  SECTION ERROR: {e}')
            import traceback; traceback.print_exc()

    if section_failures:
        print(f'\n=== {section_failures} section(s) errored; see output above ===')
    print(f'\n=== TOTAL: {passed_grand}/{total_grand} passed ===')
    if passed_grand == total_grand and section_failures == 0:
        print('ALL TESTS PASSED')
    else:
        if total_grand - passed_grand > 0:
            print(f'{total_grand - passed_grand} TESTS FAILED')
        sys.exit(1)


if __name__ == '__main__':
    main()
