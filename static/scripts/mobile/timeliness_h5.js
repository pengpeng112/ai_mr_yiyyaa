/* 病历时效质控 · 企业微信手机端 H5（2026-11-16）。
 * Vue 3 全局构建（外部脚本经 /scripts/mobile/vue.global.prod.js 桥接）；
 * CSP 禁内联脚本：全部逻辑在此文件，模板经 Vue 运行时编译（CSP 已放行 unsafe-eval）。 */
(function () {
  'use strict';

  var TOKEN_KEY = 'med_audit_mobile_token';
  var useCookieSession = false;
  var QUICK_REASONS = ['系统/网络故障', '急危重症抢救', '转科交接特殊情况', '外出会诊延误', '设备故障补录'];

  var API_BASE = '/api/mobile/timeliness';

  // ---- API 前缀自动探测：/api/mobile/timeliness 优先，公网前置机回退 /qc-api/timeliness ----
  // 3 秒超时防转圈死等（企微内核支持 AbortController）。
  function detectBase() {
    function fetchWithTimeout(url, ms) {
      var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
      var opts = { credentials: 'same-origin' };
      if (ctrl) {
        opts.signal = ctrl.signal;
        setTimeout(function () { ctrl.abort(); }, ms);
      } else {
        opts.timeout = ms; // 兼容旧内核（fetch 原生不支持时由浏览器默认超时兜底）
      }
      return fetch(url, opts);
    }
    return fetchWithTimeout('/api/mobile/timeliness/ping', 3000)
      .then(function (res) { return res.ok ? res.json() : Promise.reject(res); })
      .then(function (data) {
        if (data && data.ok) return '/api/mobile/timeliness';
        return Promise.reject(new Error('ping mismatch'));
      })
      .catch(function () {
        return fetchWithTimeout('/qc-api/timeliness/ping', 3000)
          .then(function (res) { return res.ok ? res.json() : Promise.reject(res); })
          .then(function (data) {
            if (data && data.ok) return '/qc-api/timeliness';
            return '/api/mobile/timeliness';
          })
          .catch(function () { return '/api/mobile/timeliness'; });
      });
  }

  function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ''; }
    catch (e) { return ''; }
  }
  function setToken(token) {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch (e) { /* 隐私模式 */ }
  }

  var state = {
    ready: false,
    logged: false,
    tab: 'unlock',
    toast: null,
    toastTimer: null,
    // 登录
    loginForm: { username: '', password: '' },
    loginError: '',
    loginBusy: false,
    showPwd: false,
    // 会话
    me: { full_name: '', role_label: '', dept_name: '' },
    caps: { can_approve: false, can_exempt: false, jhemr_write_enabled: false },
    passwordSetup: { open: false, initial: '', next: '', confirm: '', busy: false, error: '' },
    overview: {
      pending_approvals: 0, today_approvals: 0, month_approvals_total: 0,
      month_approved: 0, month_exempt: 0, month_penalty_amount: 0,
      in_hosp_overdue: 0, in_hosp_warning: 0, in_hosp_applying: 0,
      last_scan_at: null, jhemr_write_enabled: false,
    },
    syncing: false,
    // 字典
    dicts: { departments: [], monitor_items: [], rules: [] },
    // Tab1 审批列表
    filter: { tab: 'all', keyword: '', dept: '', monitor_code: '' },
    approvals: [], approvalsTotal: 0, approvalsPage: 1, approvalsBusy: false,
    deptSheet: false, deptSheetKeyword: '',
    // Tab2 事件
    evtFilter: { status: 'OVERDUE', keyword: '', dept: '', rule_code: '' },
    events: [], eventsTotal: 0, eventsPage: 1, eventsBusy: false,
    evtDeptSheet: false, evtDeptSheetKeyword: '', evtRuleSheet: false,
    eventDetail: { visible: false, data: null },
    // Tab3 统计
    currentMonth: '',
    statsMonth: '',
    statsDept: '',
    statsSeg: 'dept',
    deptSort: 'penalty',
    stats: { summary: { on_time_rate: 100, total: 0, completed_on_time: 0, completed_late: 0, overdue: 0, warning: 0, pending: 0, approval_count: 0, approved_unlock_count: 0, exempt_count: 0, penalty_amount_total: 0 }, dept_ranking: [], rule_breakdown: [], doctor_penalties: [] },
    statsDeptSheet: false,
    // 操作抽屉
    exemptSheet: { visible: false, cancel: false, id: null, kind: 'approval', reason: '', busy: false, error: '', patient: '', dept: '', monitor_label: '' },
    approveSheet: { visible: false, id: null, busy: false, error: '', patient: '', dept: '', monitor_label: '' },
    guideSheet: false,
  };

  var APP = null;
  if (typeof Vue === 'undefined') {
    document.body.innerHTML = '<div style="padding:40px;text-align:center;color:#e53935">页面组件加载失败，请刷新重试</div>';
    return;
  }

  // ---- 工具 ----
  function showToast(text, type, ms) {
    state.toast = { text: text, type: type || 'info' };
    if (state.toastTimer) clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(function () { state.toast = null; }, ms || 2400);
  }
  function fmtMoney(v) { return Number(v || 0).toLocaleString('zh-CN'); }
  function fmtTime(v) {
    if (!v) return '';
    return String(v).replace('T', ' ').slice(5, 16);
  }
  function monthLabel(m) { return m ? m.replace('-', '年') + '月' : ''; }
  function barClass(rate) {
    var n = Number(rate || 0);
    if (n >= 90) return 'ok';
    if (n >= 70) return 'warn';
    return 'bad';
  }
  function tagClass(item) {
    if (item.penalty_exempt) return 't-purple';
    var flag = String(item.flag || '');
    if (flag === '1') return 't-red';
    if (flag === '2') return 't-green';
    return 't-gray';
  }
  function evtTagClass(evt) {
    var s = String(evt.status || '');
    if (s === 'OVERDUE') return 't-red';
    if (s === 'WARNING') return 't-orange';
    if (s === 'APPLYING') return 't-yellow';
    if (s === 'APPROVED') return 't-green';
    if (s === 'EXEMPT') return 't-purple';
    return 't-gray';
  }

  // ---- API 封装：X-Requested-With + Bearer；401 平滑切回登录 ----
  function apiFetch(path, options) {
    options = options || {};
    var headers = Object.assign({ 'X-Requested-With': 'XMLHttpRequest' }, options.headers || {});
    var token = useCookieSession ? '' : getToken();
    // 2026-11-17 修复：无 token 时不发送 Authorization 头——
    // "Bearer "（空凭证）会让 HTTPBearer(auto_error) 直接 403，且 403 不走 401 分支导致永久转圈。
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return fetch(API_BASE + path, Object.assign({}, options, {
      headers: headers,
      credentials: 'same-origin',
    })).then(function (res) {
      if (res.status === 401) {
        setToken('');
        state.logged = false;
        state.loginError = '登录已过期，请重新登录';
        return Promise.reject(res);
      }
      return res;
    });
  }
  function apiGet(path) {
    return apiFetch(path).then(function (r) { return r.ok ? r.json() : Promise.reject(r); });
  }
  function apiPost(path, body) {
    return apiFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
    });
  }

  function detailMessage(result, fallback) {
    var data = (result && result.data) || {};
    var detail = data.detail || data.message;
    if (detail) return String(detail);
    return fallback;
  }

  // ---- 加载链 ----
  // 2026-11-17 转圈修复关键：/me 任何非 2xx（401/403）都 reject 进启动链 catch
  // （走工号免登或落登录页）——原 apiGet 对 403 静默 resolve 且不置 logged/ready。
  function loadMe(cookieOnly) {
    var request = cookieOnly
      ? fetch(API_BASE + '/me', { credentials: 'same-origin' })
      : apiFetch('/me');
    return request.then(function (res) {
      if (!res.ok) {
        if (!cookieOnly && res.status === 401) setToken('');
        return Promise.reject(res);
      }
      return res.json();
    }).then(function (data) {
      useCookieSession = Boolean(cookieOnly);
      if (useCookieSession) setToken('');
      state.me = data.user || {};
      state.caps = data.capabilities || {};
      state.logged = true;
    });
  }
  function loadDicts() {
    return apiGet('/dicts').then(function (data) { state.dicts = data; }).catch(function () { /* 降级 */ });
  }
  function loadOverview() {
    var params = new URLSearchParams();
    if (state.filter.dept) params.set('approval_dept', state.filter.dept);
    if (state.evtFilter.dept) params.set('event_dept', state.evtFilter.dept);
    var query = params.toString();
    return apiGet('/overview' + (query ? '?' + query : '')).then(function (data) {
      state.overview = data;
    }).catch(function () { /* 降级 */ });
  }
  function reloadApprovals(reset) {
    if (reset) state.approvalsPage = 1;
    state.approvalsBusy = true;
    var params = [
      'status_tab=' + encodeURIComponent(state.filter.tab),
      'page=' + state.approvalsPage,
      'limit=20',
    ];
    if (state.filter.keyword) params.push('keyword=' + encodeURIComponent(state.filter.keyword));
    if (state.filter.dept) params.push('dept=' + encodeURIComponent(state.filter.dept));
    if (state.filter.monitor_code) params.push('monitor_code=' + encodeURIComponent(state.filter.monitor_code));
    return apiGet('/approvals?' + params.join('&')).then(function (data) {
      if (state.approvalsPage === 1) state.approvals = data.items || [];
      else state.approvals = state.approvals.concat(data.items || []);
      state.approvalsTotal = data.total || 0;
    }).catch(function () {
      if (state.approvalsPage === 1) { state.approvals = []; state.approvalsTotal = 0; }
    }).finally(function () { state.approvalsBusy = false; });
  }
  function loadMoreApprovals() { state.approvalsPage += 1; return reloadApprovals(false); }
  function reloadEvents(reset) {
    if (reset) state.eventsPage = 1;
    state.eventsBusy = true;
    var params = [
      'status=' + encodeURIComponent(state.evtFilter.status),
      'page=' + state.eventsPage,
      'limit=20',
    ];
    if (state.evtFilter.keyword) params.push('keyword=' + encodeURIComponent(state.evtFilter.keyword));
    if (state.evtFilter.dept) params.push('dept=' + encodeURIComponent(state.evtFilter.dept));
    if (state.evtFilter.rule_code) params.push('rule_code=' + encodeURIComponent(state.evtFilter.rule_code));
    return apiGet('/events?' + params.join('&')).then(function (data) {
      if (state.eventsPage === 1) state.events = data.items || [];
      else state.events = state.events.concat(data.items || []);
      state.eventsTotal = data.total || 0;
    }).catch(function () {
      if (state.eventsPage === 1) { state.events = []; state.eventsTotal = 0; }
    }).finally(function () { state.eventsBusy = false; });
  }
  function loadMoreEvents() { state.eventsPage += 1; return reloadEvents(false); }
  function loadStats() {
    var params = ['month=' + encodeURIComponent(state.statsMonth)];
    if (state.statsDept) params.push('dept=' + encodeURIComponent(state.statsDept));
    return apiGet('/stats?' + params.join('&')).then(function (data) { state.stats = data; }).catch(function () { /* 保留旧值 */ });
  }

  // ---- 登录/登出 ----
  function doLogin() {
    state.loginBusy = true;
    state.loginError = '';
    fetch(API_BASE + '/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      body: JSON.stringify({ username: state.loginForm.username, password: state.loginForm.password }),
    }).then(function (res) {
      return res.json().then(function (data) { return { ok: res.ok, data: data }; });
    }).then(function (r) {
      if (!r.ok || !r.data.access_token) {
        var detail = (r.data && (r.data.detail || r.data.message)) || '登录失败，请检查账号密码';
        state.loginError = String(detail);
        return;
      }
      setToken(r.data.access_token);
      useCookieSession = false;
      state.loginForm.password = '';
      return loadMe().then(bootMainData);
    }).catch(function () {
      state.loginError = '网络连接失败，请稍后重试';
    }).finally(function () { state.loginBusy = false; });
  }

  // ---- 工号免登（2026-11-17：企微嵌入传参 ?empno=工号） ----
  function urlEmpno() {
    try {
      var params = new URLSearchParams(window.location.search);
      return (params.get('empno') || '').trim();
    } catch (e) { return ''; }
  }
  function doEmpnoLogin(empno) {
    fetch(API_BASE + '/login/empno', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      body: JSON.stringify({ empno: empno }),
    }).then(function (res) {
      return res.json().then(function (data) { return { ok: res.ok, data: data }; });
    }).then(function (r) {
      if (!r.ok || !r.data.access_token) {
        var detail = (r.data && (r.data.detail || r.data.message)) || '工号免登失败';
        state.loginError = '工号免登失败：' + detail + '。请改用手动登录。';
        state.ready = true;
        return;
      }
      setToken(r.data.access_token);
      return loadMe().then(bootMainData);
    }).catch(function () {
      state.loginError = '工号免登失败：网络连接异常。请改用手动登录。';
      state.ready = true;
    });
  }
  function doLogout() {
    apiFetch('/logout', { method: 'POST' }).then(function (res) {
      if (!res.ok) throw res;
      setToken('');
      window.location.replace(window.location.pathname);
    }).catch(function () {
      showToast('退出失败，请稍后重试', 'error');
    });
  }
  function bootMainData() {
    return loadDicts().then(function () {
      var defaultDept = state.dicts.default_dept || '';
      state.filter.dept = defaultDept;
      state.evtFilter.dept = defaultDept;
      state.statsDept = defaultDept;
      state.ready = true;
      return Promise.all([loadOverview(), reloadApprovals(true), reloadEvents(true), loadStats()]);
    });
  }

  // ---- Vue 应用 ----
  APP = Vue.createApp({
    data: function () { return state; },
    computed: {
      QUICK_REASONS: function () { return QUICK_REASONS; },
      statsMonthLabel: function () { return monthLabel(this.statsMonth); },
      deptSortKey: function () {
        if (this.deptSort === 'overdue') return 'overdue';
        if (this.deptSort === 'on_time') return 'on_time';
        return 'penalty';
      },
      sortedDeptRanking: function () {
        var rows = (this.stats.dept_ranking || []).slice();
        var sort = this.deptSort;
        rows.sort(function (a, b) {
          if (sort === 'overdue') return b.overdue - a.overdue;
          if (sort === 'on_time') return a.on_time_rate - b.on_time_rate;
          return b.penalty_amount_total - a.penalty_amount_total;
        });
        return rows;
      },
      filteredDeptOptions: function () {
        var kw = (this.deptSheetKeyword || '').toLowerCase();
        var rows = this.dicts.departments || [];
        if (!kw) return rows;
        return rows.filter(function (d) {
          return String(d.name || '').toLowerCase().indexOf(kw) >= 0
            || String(d.code || '').toLowerCase().indexOf(kw) >= 0;
        });
      },
      filteredEvtDeptOptions: function () {
        var kw = (this.evtDeptSheetKeyword || '').toLowerCase();
        var rows = this.dicts.departments || [];
        if (!kw) return rows;
        return rows.filter(function (d) {
          return String(d.name || '').toLowerCase().indexOf(kw) >= 0
            || String(d.code || '').toLowerCase().indexOf(kw) >= 0;
        });
      },
      evtRuleName: function () {
        if (!this.evtFilter.rule_code) return '';
        var hit = (this.dicts.rules || []).filter(function (r) { return r.rule_code === this.evtFilter.rule_code; }.bind(this))[0];
        return hit ? hit.rule_name : this.evtFilter.rule_code;
      },
      statsDeptName: function () {
        if (!this.statsDept) return '';
        var hit = (this.dicts.departments || []).filter(function (d) { return (d.code || d.name) === this.statsDept; }.bind(this))[0];
        return hit ? hit.name : this.statsDept;
      },
    },
    methods: {
      fmtMoney: fmtMoney,
      fmtTime: fmtTime,
      barClass: barClass,
      tagClass: tagClass,
      evtTagClass: evtTagClass,
      statusLabel: function (s) {
        var map = {
          PENDING: '未到期', OVERDUE: '已超时未签', WARNING: '临期预警',
          APPLYING: '申请解锁中', APPROVED: '已解锁待签', EXEMPT: '已豁免',
          COMPLETED_ON_TIME: '按时完成', COMPLETED_LATE: '超时完成', CANCELLED: '已取消',
        };
        return map[s] || s;
      },
      deptName: function (code) {
        if (!code) return '';
        var hit = (this.dicts.departments || []).filter(function (d) { return (d.code || d.name) === code; })[0];
        return hit ? hit.name : code;
      },
      doLogin: doLogin,
      doLogout: doLogout,
      closePasswordSetup: function () {
        if (state.passwordSetup.busy) return;
        state.passwordSetup = { open: false, initial: '', next: '', confirm: '', busy: false, error: '' };
      },
      submitPasswordSetup: function () {
        var form = state.passwordSetup;
        if (form.busy) return;
        form.error = '';
        if (form.next !== form.confirm) {
          form.error = '两次输入的个人密码不一致';
          return;
        }
        form.busy = true;
        apiPost('/me', { initial_password: form.initial, new_password: form.next }).then(function (result) {
          if (!result.ok) {
            form.error = typeof result.data.detail === 'string' ? result.data.detail : '设置失败，请检查密码要求';
            return;
          }
          state.caps.password_setup_required = false;
          state.passwordSetup = { open: false, initial: '', next: '', confirm: '', busy: false, error: '' };
          showToast('设置成功，可以用工号和个人密码登录电脑端', 'success');
        }).catch(function () {
          form.error = '网络或会话已失效，请重新从企业微信工作台进入';
        }).finally(function () {
          form.busy = false;
        });
      },
      switchTab: function (t) {
        this.tab = t;
        if (t === 'unlock') { loadOverview(); reloadApprovals(true); }
        if (t === 'events') { loadOverview(); reloadEvents(true); }
        if (t === 'stats') { loadOverview(); loadStats(); }
      },
      setTabFilter: function (t) {
        this.filter.tab = t;
        if (t === 'pending') this.filter.keyword = '';
        this.reloadApprovals(true);
      },
      setMonitorFilter: function (code) {
        this.filter.monitor_code = code;
        this.reloadApprovals(true);
      },
      clearKeyword: function () {
        this.filter.keyword = '';
        this.reloadApprovals(true);
      },
      reloadApprovals: reloadApprovals,
      loadMoreApprovals: loadMoreApprovals,
      reloadEvents: reloadEvents,
      loadMoreEvents: loadMoreEvents,
      setEvtStatus: function (s) {
        this.evtFilter.status = s;
        this.reloadEvents(true);
      },
      pickDept: function (code) {
        this.filter.dept = code;
        this.deptSheet = false;
        this.reloadApprovals(true);
        loadOverview();
      },
      pickEvtDept: function (code) {
        this.evtFilter.dept = code;
        this.evtDeptSheet = false;
        this.reloadEvents(true);
        loadOverview();
      },
      pickEvtRule: function (code) {
        this.evtFilter.rule_code = code;
        this.evtRuleSheet = false;
        this.reloadEvents(true);
      },
      pickStatsDept: function (code) {
        this.statsDept = code;
        this.statsDeptSheet = false;
        loadStats();
      },
      shiftMonth: function (delta) {
        var parts = this.statsMonth.split('-');
        var y = Number(parts[0]);
        var m = Number(parts[1]) + delta;
        if (m <= 0) { m += 12; y -= 1; }
        if (m > 12) { m -= 12; y += 1; }
        var next = y + '-' + (m < 10 ? '0' + m : m);
        if (next > this.currentMonth) return;
        this.statsMonth = next;
        loadStats();
      },
      jumpDept: function (d) {
        this.filter.dept = d.dept_code || d.dept_name;
        this.filter.tab = 'all';
        this.switchTab('unlock');
        this.reloadApprovals(true);
      },
      doSync: function () {
        if (this.syncing) return;
        this.syncing = true;
        if (!state.caps.can_sync) {
          Promise.all([loadOverview(), reloadApprovals(true)]).finally(function () { state.syncing = false; });
          return;
        }
        apiPost('/approvals/sync').then(function (r) {
          if (!r.ok) {
            showToast(detailMessage(r, '同步失败，请稍后重试'), 'error');
            return;
          }
          if (r.data && r.data.throttled) {
            showToast('刚完成同步，请稍后再试', 'info');
            return;
          }
          var data = (r.data && r.data.data) || {};
          showToast('同步完成：新增 ' + (data.approvals_inserted || 0) + ' 条，更新 ' + (data.approvals_updated || 0) + ' 条', 'success');
        }).catch(function () {
          showToast('同步失败，请检查网络', 'error');
        }).finally(function () {
          state.syncing = false;
          loadOverview();
          reloadApprovals(true);
        });
      },
      // ---- 豁免（审批与事件共用一个抽屉） ----
      openExempt: function (item) {
        this.exemptSheet = {
          visible: true, cancel: item.penalty_exempt === true, id: item.id, kind: 'approval',
          reason: '', busy: false, error: '',
          patient: (item.patient_name || item.patient_id),
          dept: item.dept_name || item.dept_code || '未知科室',
          monitor_label: item.monitor_label || '',
        };
      },
      openEventExempt: function (evt) {
        this.eventDetail.visible = false;
        this.exemptSheet = {
          visible: true, cancel: false, id: evt.id, kind: 'event',
          reason: '', busy: false, error: '',
          patient: (evt.patient_name || evt.patient_id),
          dept: evt.dept_name || evt.dept_code || '未知科室',
          monitor_label: evt.rule_name || evt.rule_code || '',
        };
      },
      submitExempt: function () {
        var sheet = this.exemptSheet;
        if (!sheet.reason.trim() || sheet.busy) return;
        sheet.busy = true;
        sheet.error = '';
        var path = sheet.kind === 'event'
          ? ('/events/' + sheet.id + '/exempt')
          : ('/approvals/' + sheet.id + '/exempt');
        apiPost(path, { exempt_reason: sheet.reason.trim(), cancel: sheet.cancel === true })
          .then(function (r) {
            if (!r.ok) {
              if (r.status === 403) sheet.error = '需要时效管理员权限，请联系医务部管理员操作';
              else sheet.error = detailMessage(r, '操作失败，请稍后重试');
              return;
            }
            sheet.visible = false;
            showToast(sheet.cancel ? '已取消豁免' : '豁免提交成功', 'success');
            loadOverview();
            if (sheet.kind === 'event') reloadEvents(true); else reloadApprovals(false);
          })
          .catch(function () { sheet.error = '网络连接失败，请稍后重试'; })
          .finally(function () { sheet.busy = false; });
      },
      // ---- 同意解锁 ----
      openApprove: function (item) {
        if (!this.caps.jhemr_write_enabled) { this.guideSheet = true; return; }
        this.approveSheet = {
          visible: true, id: item.id, busy: false, error: '',
          patient: (item.patient_name || item.patient_id),
          dept: item.dept_name || item.dept_code || '未知科室',
          monitor_label: item.monitor_label || '',
        };
      },
      submitApprove: function () {
        var sheet = this.approveSheet;
        if (sheet.busy) return;
        sheet.busy = true;
        sheet.error = '';
        apiPost('/approvals/' + sheet.id + '/approve', { dry_run: false })
          .then(function (r) {
            if (r.status === 409) { sheet.visible = false; state.guideSheet = true; return; }
            if (!r.ok) { sheet.error = detailMessage(r, '解锁失败，请稍后重试'); return; }
            sheet.visible = false;
            showToast('解锁成功，台账已更新', 'success');
            loadOverview();
            reloadApprovals(false);
          })
          .catch(function () { sheet.error = '网络连接失败，请稍后重试'; })
          .finally(function () { sheet.busy = false; });
      },
      // ---- 事件详情 ----
      openEventDetail: function (evt) {
        this.eventDetail = { visible: true, data: null };
        apiGet('/events/' + evt.id)
          .then(function (data) { state.eventDetail.data = data; })
          .catch(function () {
            state.eventDetail.visible = false;
            showToast('事件详情加载失败', 'error');
          });
      },
    },
  });

  // ---- 启动：挂载 Vue → 探测 API 前缀 → URL 工号免登 / 既有 Token 会话 / 登录页 ----
  // 2026-11-17 白屏修复：createApp 之后必须显式 mount('#app')，否则 v-cloak 永留白屏。
  // 2026-11-17 转圈根修：外部闭包直接给 state 原始对象赋值不会触发 Vue 视图更新
  // （data 返回值会被 Vue 包装成另一个 proxy）→ ready 实际已 true 但界面永远停在 loading。
  // 用 Vue.reactive 包装后再交给 data，使闭包 state 与组件内部是同一个 proxy，赋值即响应式。
  state = Vue.reactive(state);
  APP.mount('#app');

  // 2026-11-17 转圈兜底：启动链任何未知路径 8 秒未就绪 → 强制落登录页（永不永久转圈）。
  setTimeout(function () {
    if (!state.ready) {
      state.ready = true;
      state.loginError = '会话初始化超时，请重新登录';
    }
  }, 8000);

  detectBase().then(function (base) {
    API_BASE = base;
    var empno = urlEmpno();
    // OAuth 已验证的 Cookie 优先，避免旧设备 Token 覆盖企微当前身份。
    loadMe(true).catch(function (err) {
      return getToken() ? loadMe() : Promise.reject(err);
    }).then(bootMainData).catch(function () {
      if (empno) { doEmpnoLogin(empno); return; }
      state.ready = true;
    });
  });
})();
