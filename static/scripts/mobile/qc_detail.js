const ALERT_ID = window.__QC_ALERT_ID__ || '';
const TOKEN = window.__QC_TOKEN__ || '';

const VIEWER_USERID = new URLSearchParams(window.location.search).get('viewer_userid') || '';
const VIEWER_NAME = decodeURIComponent(new URLSearchParams(window.location.search).get('viewer_name') || '');

function getApiBase() {
  return '/qc-api';
}

const API_BASE = getApiBase();

const { createApp, ref, reactive, onMounted } = Vue;

const app = createApp({
  setup() {
    const loading = ref(true);
    const error = ref('');
    const alert = ref({});
    const dd = ref({});
    const cc = ref({});
    const feedback = ref({});
    const submitting = ref(false);
    const open = reactive({ exp: false, med: false, nur: false, conc: false });
    const modal = reactive({ show: false, title: '', placeholder: '', text: '', action: '' });

    function toggle(key) { open[key] = !open[key]; }

    function actionLabel(action) {
      if (action === 'acknowledged') return '已知晓';
      if (action === 'rectified') return '已处理';
      if (action === 'other') return '其他原因';
      return action;
    }

    async function loadDetail() {
      try {
        const resp = await fetch(`${API_BASE}/qc-detail/${ALERT_ID}?token=${encodeURIComponent(TOKEN)}`);
        if (resp.status === 401) { error.value = '链接已过期或无效'; loading.value = false; return; }
        if (resp.status === 404) { error.value = '质控记录不存在'; loading.value = false; return; }
        if (!resp.ok) { error.value = '加载失败'; loading.value = false; return; }
        const data = await resp.json();
        alert.value = data.alert || {};
        dd.value = data.dimension_detail || {};
        cc.value = data.conclusion || {};
        feedback.value = data.feedback || {};
      } catch (e) {
        error.value = '网络异常，请稍后重试';
      } finally {
        loading.value = false;
      }
    }

    async function submitAction(action, reason, rectText) {
      submitting.value = true;
      try {
        const body = {
          alert_id: parseInt(ALERT_ID),
          token: TOKEN,
          action,
          reason: reason || '',
          rectification_text: rectText || '',
          viewer_userid: VIEWER_USERID,
          viewer_name: VIEWER_NAME,
        };
        const resp = await fetch(`${API_BASE}/qc-feedback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (resp.status === 409) {
          window.alert('已反馈过，不可重复提交');
          await loadDetail();
          return;
        }
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          window.alert(err.detail || '提交失败');
          return;
        }
        await loadDetail();
      } catch (e) {
        window.alert('网络异常，请稍后重试');
      } finally {
        submitting.value = false;
      }
    }

    function doFeedback(action) {
      if (action === 'acknowledged') {
        submitAction('acknowledged');
        return;
      }
      if (action === 'rectified') {
        modal.show = true;
        modal.title = '已处理';
        modal.placeholder = '请填写整改说明（必填）';
        modal.text = '';
        modal.action = 'rectified';
        return;
      }
      if (action === 'other') {
        modal.show = true;
        modal.title = '其他原因';
        modal.placeholder = '请填写原因说明（必填）';
        modal.text = '';
        modal.action = 'other';
        return;
      }
    }

    function modalConfirm() {
      const text = (modal.text || '').trim();
      if (!text) {
        window.alert(modal.action === 'rectified' ? '请填写整改说明' : '请填写原因说明');
        return;
      }
      modal.show = false;
      if (modal.action === 'rectified') {
        submitAction('rectified', '', text);
      } else {
        submitAction('other', text, '');
      }
    }

    onMounted(loadDetail);

    return {
      loading, error, alert, dd, cc, feedback, submitting, open, modal,
      toggle, actionLabel, doFeedback, modalConfirm,
    };
  },
});

app.mount('#app');
